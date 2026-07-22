"""Deterministic policy rules used by the capability broker."""

from __future__ import annotations

from dataclasses import dataclass

from living_agent.models.capabilities import DecisionOutcome
from living_agent.models.events import AuthorityLevel


@dataclass(frozen=True, slots=True)
class PolicyRuleSet:
    write_operations: frozenset[str] = frozenset(
        {
            "write",
            "create",
            "update",
            "delete",
            "install",
            "enable",
            "disable",
            "send",
            "reply",
            "embed",
        }
    )
    configured_system_operations: frozenset[str] = frozenset({"reply", "embed"})
    self_modification_capabilities: frozenset[str] = frozenset(
        {"config.modify", "persona.modify", "prompt.modify", "plugin.install"}
    )

    def operation_class(self, operation: str) -> str:
        return "write" if operation.lower() in self.write_operations else "read"

    def confirmation_outcome(
        self,
        *,
        authority: AuthorityLevel,
        operation: str,
        confirmed_by: str | None,
        owner_id: str,
    ) -> DecisionOutcome | None:
        if self.operation_class(operation) != "write":
            return None
        if (
            operation.lower() in self.configured_system_operations
            and authority is AuthorityLevel.SYSTEM
        ):
            return None
        if confirmed_by == owner_id:
            return None
        if authority in {AuthorityLevel.OWNER, AuthorityLevel.ADMIN}:
            return DecisionOutcome.ASK_OWNER
        return DecisionOutcome.DENY
