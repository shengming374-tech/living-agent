"""Evidence gate for observable continuity claims, not hidden reasoning."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from living_agent.audit.service import AuditService
from living_agent.memory.service import MemoryAccessError, MemoryService
from living_agent.models.claims import ClaimEvidence
from living_agent.models.psyche import ActivityStatus
from living_agent.psyche.service import PsycheService


class CriticAction(StrEnum):
    APPROVE = "approve"
    BLOCK = "block"
    REMOVE_UNIT = "remove_unit"
    SHORTEN_UNIT = "shorten_unit"
    REGENERATE_UNIT = "regenerate_unit"
    REQUEST_VERIFICATION = "request_verification"


class ContinuityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: CriticAction
    reason_codes: list[str] = Field(default_factory=list)


class ContinuityCritic:
    _memory_claim = re.compile(r"\bI\s+(?:still\s+)?remember\b|我(?:还)?记得", re.IGNORECASE)
    _thought_claim = re.compile(
        r"\bI\s+(?:was\s+thinking|thought)\s+(?:about\s+)?(?:that|this)\s+(?:earlier|before)\b"
        r"|我(?:刚才|之前)想过",
        re.IGNORECASE,
    )
    _changed_view_claim = re.compile(
        r"\bI\s+(?:changed my mind|used to think)\b|我(?:改变了看法|之前认为)",
        re.IGNORECASE,
    )
    _action_claim = re.compile(
        r"\bI\s+(?:completed|finished|sent|wrote|did)\b|我(?:完成了|发送了|写了|做过)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        psyche: PsycheService,
        memories: MemoryService,
        audit: AuditService,
    ) -> None:
        self._psyche = psyche
        self._memories = memories
        self._audit = audit

    async def evaluate(
        self,
        text: str,
        evidence: ClaimEvidence,
        *,
        conversation_id: str | None,
        actor_id: str = "living-agent",
        evaluated_at: datetime | None = None,
    ) -> ContinuityDecision:
        now = evaluated_at or datetime.now(UTC)
        reasons: list[str] = []
        if self._memory_claim.search(text) and not await self._valid_memories(
            evidence.memory_ids,
            actor_id=actor_id,
            conversation_id=conversation_id,
        ):
            reasons.append("memory_claim_without_accessible_evidence")
        if self._thought_claim.search(text) and not await self._valid_thoughts(
            evidence.thought_record_ids,
            conversation_id=conversation_id,
            before=now,
        ):
            reasons.append("prior_thought_claim_without_earlier_record")
        if self._changed_view_claim.search(text):
            reasons.append("viewpoint_change_history_unavailable")
        if self._action_claim.search(text) and not await self._valid_actions(
            evidence,
            conversation_id=conversation_id,
        ):
            reasons.append("action_claim_without_activity_or_tool_evidence")
        return ContinuityDecision(
            action=CriticAction.BLOCK if reasons else CriticAction.APPROVE,
            reason_codes=reasons,
        )

    async def _valid_memories(
        self,
        memory_ids: list[str],
        *,
        actor_id: str,
        conversation_id: str | None,
    ) -> bool:
        if not memory_ids:
            return False
        try:
            for memory_id in memory_ids:
                await self._memories.get_accessible(
                    memory_id,
                    actor_id=actor_id,
                    conversation_id=conversation_id,
                    owner=False,
                )
        except (LookupError, MemoryAccessError):
            return False
        return True

    async def _valid_thoughts(
        self,
        thought_ids: list[str],
        *,
        conversation_id: str | None,
        before: datetime,
    ) -> bool:
        if not thought_ids:
            return False
        thoughts = await self._psyche.thoughts_by_ids(thought_ids)
        if len(thoughts) != len(thought_ids):
            return False
        if any(self._aware(thought.created_at) >= before for thought in thoughts):
            return False
        return all(
            [
                await self._psyche.sources_match_conversation(
                    thought.source_event_ids,
                    conversation_id,
                )
                for thought in thoughts
            ]
        )

    async def _valid_actions(
        self,
        evidence: ClaimEvidence,
        *,
        conversation_id: str | None,
    ) -> bool:
        if evidence.activity_ids:
            activities = await self._psyche.activities_by_ids(evidence.activity_ids)
            valid_activities = len(activities) == len(evidence.activity_ids)
            for activity in activities:
                valid_activities = valid_activities and (
                    activity.status is ActivityStatus.COMPLETED
                    and await self._psyche.sources_match_conversation(
                        activity.source_event_ids,
                        conversation_id,
                    )
                )
            if valid_activities:
                return True
        if evidence.tool_audit_ids:
            entries = await self._audit.get_entries(evidence.tool_audit_ids)
            return len(entries) == len(evidence.tool_audit_ids) and all(
                entry.action == "tool.called"
                and entry.outcome == "verified"
                and entry.conversation_id == conversation_id
                for entry in entries
            )
        return False

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
