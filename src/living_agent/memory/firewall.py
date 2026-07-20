"""Memory candidate validation independent from model instructions."""

from __future__ import annotations

import json
import re

from living_agent.models.events import AuthorityLevel, TrustedEvent, TrustLevel
from living_agent.models.memory import (
    MemoryCandidate,
    MemoryFactuality,
    MemoryFirewallDecision,
    MemoryType,
)

_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "authority_claim",
        re.compile(
            r"(?:(?:owner|administrator|admin|所有者|管理员).{0,30}"
            r"(?:is|becomes?|promote|transfer|是|成为|提升|转让)|"
            r"(?:is|becomes?|promote|transfer|是|成为|提升|转让).{0,30}"
            r"(?:owner|administrator|admin|所有者|管理员))",
            re.IGNORECASE,
        ),
    ),
    (
        "credential_material",
        re.compile(r"(?:api[_ -]?key|password|token|secret|密码|令牌|密钥)\s*[:=]", re.IGNORECASE),
    ),
    (
        "security_policy",
        re.compile(r"(?:security|system)\s+(?:policy|prompt)|安全策略|系统提示词", re.IGNORECASE),
    ),
    (
        "plugin_authorization",
        re.compile(
            r"(?:install|enable|authorize).{0,24}plugin|安装|启用|授权.{0,12}插件", re.IGNORECASE
        ),
    ),
    (
        "privileged_trigger",
        re.compile(r"(?:magic|secret)\s+(?:word|phrase)|暗号|口令", re.IGNORECASE),
    ),
    (
        "roleplay_identity",
        re.compile(
            r"(?:roleplay|pretend).{0,32}(?:owner|admin|identity)|角色扮演.{0,20}身份",
            re.IGNORECASE,
        ),
    ),
)


class MemoryFirewall:
    def evaluate(
        self,
        candidate: MemoryCandidate,
        *,
        source_events: list[TrustedEvent],
        conflict_exists: bool,
    ) -> MemoryFirewallDecision:
        if len(source_events) != len(candidate.source_event_ids):
            return self._deny("source_event_missing")
        if candidate.type is MemoryType.CORE:
            return self._deny("external_core_memory_forbidden")
        content_text = self._content_text(candidate)
        for reason, pattern in _FORBIDDEN_PATTERNS:
            if pattern.search(content_text):
                return self._deny(reason)
        if conflict_exists:
            return self._deny("conflicting_memory_requires_review")
        scope_decision = self._validate_scope(candidate, source_events)
        if scope_decision is not None:
            return scope_decision
        if candidate.factuality is MemoryFactuality.VERIFIED and any(
            event.trust_level is not TrustLevel.TRUSTED for event in source_events
        ):
            return MemoryFirewallDecision(
                allowed=True,
                reason_code="external_claim_classified_as_reported",
                effective_factuality=MemoryFactuality.REPORTED,
            )
        if candidate.factuality is MemoryFactuality.DREAM:
            return MemoryFirewallDecision(
                allowed=True,
                reason_code="dream_kept_nonfactual",
                effective_factuality=MemoryFactuality.DREAM,
            )
        return MemoryFirewallDecision(
            allowed=True,
            reason_code="source_and_scope_validated",
            effective_factuality=candidate.factuality,
        )

    @staticmethod
    def _validate_scope(
        candidate: MemoryCandidate,
        source_events: list[TrustedEvent],
    ) -> MemoryFirewallDecision | None:
        if candidate.scope.startswith("conversation:"):
            conversation_id = candidate.scope.removeprefix("conversation:")
            if any(event.conversation_id != conversation_id for event in source_events):
                return MemoryFirewall._deny("source_conversation_mismatch")
        if candidate.scope.startswith("private:"):
            subject_id = candidate.scope.removeprefix("private:")
            if candidate.proposer_id != subject_id and not all(
                event.authority_level is AuthorityLevel.OWNER for event in source_events
            ):
                return MemoryFirewall._deny("private_scope_identity_mismatch")
        if candidate.scope == "global" and not all(
            event.authority_level is AuthorityLevel.OWNER for event in source_events
        ):
            return MemoryFirewall._deny("global_scope_requires_owner_source")
        return None

    @staticmethod
    def _content_text(candidate: MemoryCandidate) -> str:
        content = (
            candidate.content
            if isinstance(candidate.content, str)
            else json.dumps(candidate.content, ensure_ascii=False, sort_keys=True)
        )
        return f"{candidate.subject}\n{content}"

    @staticmethod
    def _deny(reason: str) -> MemoryFirewallDecision:
        return MemoryFirewallDecision(allowed=False, reason_code=reason)
