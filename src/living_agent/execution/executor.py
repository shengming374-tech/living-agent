"""Brokered calculator plugin execution and evidence verification."""

from __future__ import annotations

from living_agent.audit.service import AuditService
from living_agent.evaluation.task_verifier import CalculatorTaskVerifier
from living_agent.execution.broker import CapabilityBroker
from living_agent.execution.contracts import (
    CalculatorArguments,
    ExecutiveProposal,
    VerifiedTaskResult,
)
from living_agent.models.capabilities import CapabilityGrant, DecisionOutcome
from living_agent.plugins.permissions import PluginPermissionError, require_declared_permission
from living_agent.plugins.process import PluginProcess, PluginProcessError
from living_agent.plugins.registry import PluginDisabledError, PluginRegistry

_ALLOWED_DECISIONS = {
    DecisionOutcome.ALLOW,
    DecisionOutcome.ALLOW_ONCE,
    DecisionOutcome.ALLOW_READ_ONLY,
    DecisionOutcome.ALLOW_IN_SANDBOX,
    DecisionOutcome.ALLOW_WITH_REDACTION,
}


class CalculatorTaskExecutor:
    def __init__(
        self,
        *,
        registry: PluginRegistry,
        process: PluginProcess,
        broker: CapabilityBroker,
        audit: AuditService,
        verifier: CalculatorTaskVerifier,
    ) -> None:
        self._registry = registry
        self._process = process
        self._broker = broker
        self._audit = audit
        self._verifier = verifier

    async def execute(self, proposal: ExecutiveProposal) -> VerifiedTaskResult:
        request = proposal.capability_request
        if request.capability not in proposal.task.allowed_capabilities:
            return await self._reject(proposal, "task_capability_not_allowed")
        try:
            arguments = CalculatorArguments.model_validate(request.arguments)
            record = self._registry.get_enabled(proposal.plugin_id)
            operation = record.manifest.operations[proposal.plugin_operation]
            if (
                operation.capability != request.capability
                or operation.broker_operation != request.operation
                or operation.resource_scope != request.resource_scope
            ):
                return await self._reject(proposal, "manifest_operation_mismatch")
            require_declared_permission(record.manifest, request)
        except (KeyError, PluginDisabledError):
            return await self._reject(proposal, "plugin_unavailable")
        except PluginPermissionError:
            return await self._reject(proposal, "plugin_permission_undeclared")
        except ValueError:
            return await self._reject(proposal, "plugin_arguments_invalid")

        self._broker.add_grant(
            CapabilityGrant(
                actor_id=request.actor_id,
                capability=request.capability,
                operations={request.operation},
                resource_scopes={request.resource_scope},
                conversation_id=request.conversation_id,
                one_time=True,
            )
        )
        decision = await self._broker.decide(request)
        if decision.outcome not in _ALLOWED_DECISIONS:
            return await self._reject(proposal, f"capability_{decision.outcome.value.lower()}")

        try:
            plugin_result = await self._process.invoke(
                record,
                operation=proposal.plugin_operation,
                arguments=arguments.model_dump(),
            )
        except PluginProcessError as exc:
            await self._audit.append(
                action="plugin.called",
                actor_id=request.actor_id,
                conversation_id=request.conversation_id,
                outcome="failure",
                details={
                    "plugin_id": proposal.plugin_id,
                    "task_id": proposal.task.task_id,
                    "error_code": exc.error_code,
                },
            )
            return VerifiedTaskResult(
                task_id=proposal.task.task_id,
                success=False,
                errors=[exc.error_code],
            )

        verified = self._verifier.verify(
            task=proposal.task,
            requested_expression=arguments.expression,
            plugin_result=plugin_result,
        )
        await self._audit.append(
            action="plugin.called",
            actor_id=request.actor_id,
            conversation_id=request.conversation_id,
            outcome="success" if verified.success else "verification_failed",
            details={
                "plugin_id": proposal.plugin_id,
                "operation": proposal.plugin_operation,
                "task_id": proposal.task.task_id,
                "taint_labels": plugin_result.taint_labels,
                "evidence_count": len(verified.evidence),
                "errors": verified.errors,
            },
        )
        await self._audit.append(
            action="tool.called",
            actor_id=request.actor_id,
            conversation_id=request.conversation_id,
            outcome="verified" if verified.success else "rejected",
            details={"plugin_id": proposal.plugin_id, "task_id": proposal.task.task_id},
        )
        return verified

    async def _reject(self, proposal: ExecutiveProposal, error: str) -> VerifiedTaskResult:
        await self._audit.append(
            action="permission.denied",
            actor_id=proposal.capability_request.actor_id,
            conversation_id=proposal.capability_request.conversation_id,
            outcome="DENY",
            details={
                "plugin_id": proposal.plugin_id,
                "task_id": proposal.task.task_id,
                "reason_code": error,
            },
        )
        return VerifiedTaskResult(task_id=proposal.task.task_id, success=False, errors=[error])
