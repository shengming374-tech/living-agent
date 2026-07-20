"""Confirmed host-owned task report capability."""

from __future__ import annotations

from living_agent.audit.service import AuditService
from living_agent.execution.broker import CapabilityBroker
from living_agent.execution.contracts import (
    PlannedAction,
    TaskEvidence,
    TaskStepResult,
    TaskStepStatus,
)
from living_agent.execution.report_contracts import (
    TASK_REPORT_CAPABILITY,
    VERIFIED_RESULTS_PLACEHOLDER,
    TaskReportArguments,
)
from living_agent.execution.repository import TaskConflictError, TaskRepository
from living_agent.models.capabilities import CapabilityGrant, DecisionOutcome
from living_agent.models.tasks import TaskContract

_ALLOWED_DECISIONS = {
    DecisionOutcome.ALLOW,
    DecisionOutcome.ALLOW_ONCE,
    DecisionOutcome.ALLOW_WITH_REDACTION,
}


class TaskReportExecutor:
    def __init__(
        self,
        *,
        broker: CapabilityBroker,
        repository: TaskRepository,
        audit: AuditService,
    ) -> None:
        self._broker = broker
        self._repository = repository
        self._audit = audit

    async def execute(
        self,
        *,
        task: TaskContract,
        action: PlannedAction,
        prior_results: list[TaskStepResult],
        confirmed_by: str | None,
    ) -> TaskStepResult:
        request = action.capability_request.model_copy(
            update={"arguments": self._resolved_arguments(action, prior_results)}
        )
        grant = CapabilityGrant(
            actor_id=request.actor_id,
            capability=request.capability,
            operations={request.operation},
            resource_scopes={request.resource_scope},
            conversation_id=request.conversation_id,
            one_time=True,
        )
        self._broker.add_grant(grant)
        decision = await self._broker.decide(request, confirmed_by=confirmed_by)
        if decision.outcome is DecisionOutcome.ASK_OWNER:
            self._broker.revoke_grant(grant)
            return TaskStepResult(
                step_id="pending",
                status=TaskStepStatus.WAITING_CONFIRMATION,
                confirmation_request_id=request.request_id,
            )
        if decision.outcome not in _ALLOWED_DECISIONS:
            self._broker.revoke_grant(grant)
            return TaskStepResult(
                step_id="failed",
                status=TaskStepStatus.FAILED,
                errors=[decision.reason_code],
            )

        arguments = TaskReportArguments.model_validate(request.arguments)
        try:
            report = await self._repository.write_report(
                task_id=arguments.task_id,
                content=arguments.content,
                created_by=task.requester_id,
                source_event_ids=request.source_event_ids,
            )
        except TaskConflictError:
            return TaskStepResult(
                step_id="failed",
                status=TaskStepStatus.FAILED,
                errors=["task_report_conflict"],
            )
        evidence = TaskEvidence(
            kind="database_commit",
            source="task_report_repository",
            data={"report_id": report.report_id, "task_id": report.task_id},
        )
        await self._audit.append(
            action="task.report_written",
            actor_id=task.requester_id,
            conversation_id=request.conversation_id,
            outcome="verified",
            details={
                "task_id": task.task_id,
                "report_id": report.report_id,
                "source_event_ids": request.source_event_ids,
            },
        )
        await self._audit.append(
            action="tool.called",
            actor_id=task.requester_id,
            conversation_id=request.conversation_id,
            outcome="verified",
            details={"capability": TASK_REPORT_CAPABILITY, "task_id": task.task_id},
        )
        return TaskStepResult(
            step_id="completed",
            status=TaskStepStatus.COMPLETED,
            output={"report_id": report.report_id},
            evidence=[evidence],
        )

    @staticmethod
    def _resolved_arguments(
        action: PlannedAction,
        prior_results: list[TaskStepResult],
    ) -> dict[str, object]:
        arguments = TaskReportArguments.model_validate(action.capability_request.arguments)
        lines = []
        for result in prior_results:
            output = result.output or {}
            expression = output.get("expression")
            value = output.get("value")
            if isinstance(expression, str) and isinstance(value, (int, float)):
                lines.append(f"{expression} = {value}")
        replacement = "\n".join(lines) or "No verified tool outputs."
        return {
            "task_id": arguments.task_id,
            "content": arguments.content.replace(VERIFIED_RESULTS_PLACEHOLDER, replacement),
        }
