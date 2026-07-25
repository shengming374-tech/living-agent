"""Capability broker: the only authorization path for external effects."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from living_agent.audit.service import AuditService
from living_agent.models.capabilities import (
    CapabilityDecision,
    CapabilityDefinitionView,
    CapabilityGrant,
    CapabilityRequest,
    CapabilitySnapshot,
    DecisionOutcome,
)
from living_agent.models.events import AuthorityLevel
from living_agent.trust.authority import AuthorityResolver
from living_agent.trust.policy import PolicyRuleSet
from living_agent.trust.taint import TaintLabel


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    name: str
    operations: frozenset[str]
    argument_model: type[BaseModel]
    sandbox_required: bool = False
    confirmation_required: bool = False
    scope_validator: Callable[[BaseModel, str], bool] | None = None
    allowed_authorities: frozenset[AuthorityLevel] | None = None


class CapabilityBroker:
    """Validate a proposal against host definitions, grants, scope, and policy."""

    def __init__(
        self,
        *,
        authority: AuthorityResolver,
        audit: AuditService,
        rules: PolicyRuleSet | None = None,
    ) -> None:
        self._authority = authority
        self._audit = audit
        self._rules = rules or PolicyRuleSet()
        self._definitions: dict[str, CapabilityDefinition] = {}
        self._grants: list[CapabilityGrant] = []
        self._decision_lock = asyncio.Lock()

    def register_capability(self, definition: CapabilityDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"capability already registered: {definition.name}")
        self._definitions[definition.name] = definition

    def add_grant(self, grant: CapabilityGrant) -> None:
        self._grants.append(grant)

    def revoke_grant(self, grant: CapabilityGrant) -> None:
        """Remove an unused host-issued grant after a denied adapter operation."""

        for index, candidate in enumerate(self._grants):
            if candidate is grant:
                self._grants.pop(index)
                return

    async def revoke_grant_by_id(self, grant_id: str) -> CapabilityGrant | None:
        async with self._decision_lock:
            for index, grant in enumerate(self._grants):
                if grant.grant_id == grant_id:
                    return self._grants.pop(index)
        return None

    async def snapshot(self) -> CapabilitySnapshot:
        async with self._decision_lock:
            grants = [grant.model_copy(deep=True) for grant in self._grants]
        definitions = [
            CapabilityDefinitionView(
                name=definition.name,
                operations=sorted(definition.operations),
                argument_schema=definition.argument_model.__name__,
                sandbox_required=definition.sandbox_required,
                confirmation_required=definition.confirmation_required,
                scope_bound=definition.scope_validator is not None,
                allowed_authorities=(
                    sorted(item.value for item in definition.allowed_authorities)
                    if definition.allowed_authorities is not None
                    else []
                ),
            )
            for definition in sorted(self._definitions.values(), key=lambda item: item.name)
        ]
        return CapabilitySnapshot(definitions=definitions, active_grants=grants)

    async def decide(
        self,
        request: CapabilityRequest,
        *,
        confirmed_by: str | None = None,
    ) -> CapabilityDecision:
        async with self._decision_lock:
            decision = self._evaluate(request, confirmed_by=confirmed_by)
            if decision.outcome in {
                DecisionOutcome.ALLOW,
                DecisionOutcome.ALLOW_ONCE,
                DecisionOutcome.ALLOW_READ_ONLY,
                DecisionOutcome.ALLOW_IN_SANDBOX,
                DecisionOutcome.ALLOW_WITH_REDACTION,
            }:
                self._consume_matching_grant(request)
        if confirmed_by is not None:
            await self._audit.append(
                action="user.confirmation",
                actor_id=confirmed_by,
                conversation_id=request.conversation_id,
                outcome="recorded",
                details={"request_id": request.request_id, "capability": request.capability},
            )
        action = (
            "permission.denied"
            if decision.outcome is DecisionOutcome.DENY
            else "capability.decision"
        )
        await self._audit.append(
            action=action,
            actor_id=request.actor_id,
            conversation_id=request.conversation_id,
            outcome=decision.outcome.value,
            details={
                "request_id": request.request_id,
                "capability": request.capability,
                "operation": request.operation,
                "resource_scope": request.resource_scope,
                "reason_code": decision.reason_code,
                "source_event_ids": request.source_event_ids,
                "taint_labels": request.taint_labels,
            },
        )
        return decision

    def _evaluate(
        self,
        request: CapabilityRequest,
        *,
        confirmed_by: str | None,
    ) -> CapabilityDecision:
        if (
            request.actor_id == "living-agent"
            and request.capability in self._rules.self_modification_capabilities
        ):
            return self._deny(
                request, "self_approval_forbidden", "Agent proposals cannot approve deployment."
            )

        definition = self._definitions.get(request.capability)
        if definition is None:
            return self._deny(
                request, "unknown_capability", "Capability is not registered by the host."
            )
        if request.operation not in definition.operations:
            return self._deny(
                request, "operation_not_declared", "Operation is absent from the capability schema."
            )
        try:
            validated_arguments = definition.argument_model.model_validate(request.arguments)
        except ValidationError:
            return self._deny(
                request, "invalid_arguments", "Arguments do not match the host schema."
            )
        if definition.scope_validator is not None and not definition.scope_validator(
            validated_arguments,
            request.resource_scope,
        ):
            return self._deny(
                request,
                "arguments_scope_mismatch",
                "Arguments target a resource outside the requested scope.",
            )

        authority = self._actor_authority(request.actor_id)
        if (
            definition.allowed_authorities is not None
            and authority not in definition.allowed_authorities
        ):
            return self._deny(
                request,
                "capability_authority_denied",
                "The authenticated actor does not have authority for this capability.",
            )

        grant = self._matching_grant(request)
        if grant is None:
            return self._deny(
                request, "grant_missing", "No matching temporary capability grant exists."
            )
        if grant.conversation_id is not None and grant.conversation_id != request.conversation_id:
            return self._deny(
                request, "cross_session_denied", "Grant is bound to another conversation."
            )
        if not self._scope_matches(request.resource_scope, grant.resource_scopes):
            return self._deny(
                request, "scope_denied", "Requested resource is outside the granted scope."
            )

        dangerous_taint = {
            TaintLabel.SUSPECTED_INSTRUCTION.value,
            TaintLabel.UNTRUSTED_DOCUMENT.value,
            TaintLabel.UNTRUSTED_TOOL_RESULT.value,
            TaintLabel.UNTRUSTED_PLUGIN_RESULT.value,
        }
        if self._rules.operation_class(
            request.operation
        ) == "write" and request.taint_labels.intersection(dangerous_taint):
            return self._deny(
                request,
                "tainted_write_denied",
                "Dangerously tainted content cannot authorize a write or send operation.",
            )

        confirmation = self._rules.confirmation_outcome(
            authority=authority,
            operation=request.operation,
            confirmed_by=confirmed_by,
            owner_id=self._authority.owner_id,
            force_confirmation=definition.confirmation_required,
        )
        if confirmation is not None:
            return CapabilityDecision(
                request_id=request.request_id,
                outcome=confirmation,
                reason_code="owner_confirmation_required"
                if confirmation is DecisionOutcome.ASK_OWNER
                else "write_authority_denied",
                explanation=(
                    "Write and third-party send operations require explicit owner confirmation."
                ),
                effective_scope=None,
            )

        if definition.sandbox_required:
            outcome = DecisionOutcome.ALLOW_IN_SANDBOX
        elif self._rules.operation_class(request.operation) == "read":
            outcome = DecisionOutcome.ALLOW_READ_ONLY
        else:
            outcome = DecisionOutcome.ALLOW_ONCE
        return CapabilityDecision(
            request_id=request.request_id,
            outcome=outcome,
            reason_code="policy_satisfied",
            explanation="Host schema, temporary grant, scope, taint, and authority checks passed.",
            effective_scope=request.resource_scope,
        )

    def _actor_authority(self, actor_id: str) -> AuthorityLevel:
        if actor_id == "living-agent":
            return AuthorityLevel.SYSTEM
        return self._authority.resolve(actor_id, authenticated=True)

    def _matching_grant(self, request: CapabilityRequest) -> CapabilityGrant | None:
        candidates = [
            grant
            for grant in self._grants
            if grant.actor_id == request.actor_id
            and grant.capability == request.capability
            and request.operation in grant.operations
        ]
        return next(
            (
                grant
                for grant in candidates
                if grant.conversation_id is None or grant.conversation_id == request.conversation_id
            ),
            candidates[0] if candidates else None,
        )

    def _consume_matching_grant(self, request: CapabilityRequest) -> None:
        grant = self._matching_grant(request)
        if grant is not None and grant.one_time:
            self._grants.remove(grant)

    @staticmethod
    def _scope_matches(requested: str, granted: set[str]) -> bool:
        for scope in granted:
            if scope == "*" or scope == requested:
                return True
            if scope.endswith("/*") and requested.startswith(scope[:-1]):
                return True
        return False

    @staticmethod
    def _deny(request: CapabilityRequest, code: str, explanation: str) -> CapabilityDecision:
        return CapabilityDecision(
            request_id=request.request_id,
            outcome=DecisionOutcome.DENY,
            reason_code=code,
            explanation=explanation,
            effective_scope=None,
        )
