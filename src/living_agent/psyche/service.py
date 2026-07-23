"""Audited psyche appraisal, decay, thought, topic, and activity workflows."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from living_agent.audit.service import AuditService, redact_text
from living_agent.models.conversation import TurnDecision
from living_agent.models.events import TrustedEvent
from living_agent.models.psyche import (
    ActivityRecord,
    PsycheState,
    PsycheStateUpdate,
    ThoughtRecord,
    ThoughtRecordCreate,
    UnresolvedTopic,
    UnresolvedTopicCreate,
)
from living_agent.psyche.repository import PsycheRepository
from living_agent.storage.events import EventRepository


class PsycheSourceError(ValueError):
    pass


class PsycheService:
    def __init__(
        self,
        *,
        repository: PsycheRepository,
        events: EventRepository,
        audit: AuditService,
        decay_half_life_hours: float,
    ) -> None:
        self._repository = repository
        self._events = events
        self._audit = audit
        self._decay_half_life_hours = decay_half_life_hours
        self._state_lock = asyncio.Lock()

    async def initialize(self) -> PsycheState:
        await self._repository.initialize()
        return await self.decay(actor_id="living-agent", audit_if_changed=False)

    async def state(self) -> PsycheState:
        return await self._repository.state()

    async def update_state(
        self,
        update: PsycheStateUpdate,
        *,
        actor_id: str,
    ) -> PsycheState:
        async with self._state_lock:
            state = await self._repository.update_state(update)
        await self._audit.append(
            action="psyche.updated",
            actor_id=actor_id,
            outcome="success",
            details={"version": state.version, "changed_fields": sorted(update.model_fields_set)},
        )
        return state

    async def decay(
        self,
        *,
        actor_id: str,
        now: datetime | None = None,
        audit_if_changed: bool = True,
    ) -> PsycheState:
        current = await self._repository.state()
        target = now or datetime.now(UTC)
        async with self._state_lock:
            state = await self._repository.apply_decay(
                now=target,
                half_life_hours=self._decay_half_life_hours,
            )
        if audit_if_changed and state.version != current.version:
            await self._audit.append(
                action="psyche.decayed",
                actor_id=actor_id,
                outcome="success",
                details={
                    "from_version": current.version,
                    "to_version": state.version,
                    "valence": state.valence,
                    "arousal": state.arousal,
                    "focus_salience": state.focus_salience,
                },
            )
        return state

    async def appraise(self, event: TrustedEvent, turn: TurnDecision) -> ThoughtRecord:
        now = datetime.now(UTC)
        focus = self._focus_summary(event)
        if turn.mode == "observe":
            create = ThoughtRecordCreate(
                kind="suppressed_reply",
                summary=(
                    f"注意到当前话题“{focus}”\uff0c但这轮保持安静"
                    f"\uff0c原因是 {turn.reason_code}"
                ),
                source_event_ids=[event.event_id],
                intensity=turn.urgency,
                speakability=0.0,
                expires_at=now + timedelta(hours=24),
            )
        else:
            create = ThoughtRecordCreate(
                kind="reaction",
                summary=(
                    f"注意力落在“{focus}”上\uff0c准备以 {turn.mode} 方式参与"
                    f"\uff0c原因是 {turn.reason_code}"
                ),
                source_event_ids=[event.event_id],
                intensity=turn.urgency,
                speakability=min(1.0, 0.4 + turn.urgency / 2),
                expires_at=now + timedelta(hours=72),
            )
        thought = await self.create_thought(create, actor_id="living-agent")
        if turn.mode != "observe":
            await self.update_state(
                PsycheStateUpdate(
                    current_focus=focus,
                    focus_salience=max(0.1, turn.urgency),
                    arousal=max(0.1, turn.urgency),
                ),
                actor_id="living-agent",
            )
        return thought

    async def create_thought(
        self,
        create: ThoughtRecordCreate,
        *,
        actor_id: str,
    ) -> ThoughtRecord:
        await self._require_sources(create.source_event_ids)
        thought = await self._repository.create_thought(create)
        await self._audit.append(
            action="thought.created",
            actor_id=actor_id,
            outcome="success",
            details={
                "thought_id": thought.thought_id,
                "kind": thought.kind,
                "source_event_ids": thought.source_event_ids,
                "intensity": thought.intensity,
                "speakability": thought.speakability,
            },
        )
        return thought

    async def thoughts(
        self,
        *,
        include_resolved: bool = False,
        limit: int = 100,
    ) -> list[ThoughtRecord]:
        return await self._repository.thoughts(
            include_resolved=include_resolved,
            limit=limit,
        )

    async def thoughts_by_ids(self, thought_ids: list[str]) -> list[ThoughtRecord]:
        return await self._repository.thoughts_by_ids(thought_ids)

    async def resolve_thought(self, thought_id: str, *, actor_id: str) -> ThoughtRecord:
        thought = await self._repository.resolve_thought(thought_id)
        await self._audit.append(
            action="thought.resolved",
            actor_id=actor_id,
            outcome="success",
            details={"thought_id": thought_id},
        )
        return thought

    async def create_topic(
        self,
        create: UnresolvedTopicCreate,
        *,
        actor_id: str,
    ) -> UnresolvedTopic:
        await self._require_sources(create.source_event_ids)
        async with self._state_lock:
            topic = await self._repository.create_topic(create)
        await self._audit.append(
            action="psyche.topic_created",
            actor_id=actor_id,
            outcome="success",
            details={"topic_id": topic.topic_id, "source_event_ids": topic.source_event_ids},
        )
        return topic

    async def topics(self, *, include_resolved: bool = False) -> list[UnresolvedTopic]:
        return await self._repository.topics(include_resolved=include_resolved)

    async def resolve_topic(self, topic_id: str, *, actor_id: str) -> UnresolvedTopic:
        async with self._state_lock:
            topic = await self._repository.resolve_topic(topic_id)
        await self._audit.append(
            action="psyche.topic_resolved",
            actor_id=actor_id,
            outcome="success",
            details={"topic_id": topic_id},
        )
        return topic

    async def start_activity(
        self,
        *,
        kind: str,
        summary: str,
        source_event_ids: list[str],
    ) -> ActivityRecord:
        await self._require_sources(source_event_ids)
        async with self._state_lock:
            activity = await self._repository.start_activity(
                kind=kind,
                summary=summary,
                source_event_ids=source_event_ids,
            )
        await self._audit.append(
            action="activity.started",
            actor_id="living-agent",
            outcome="running",
            details={"activity_id": activity.activity_id, "kind": kind},
        )
        return activity

    async def finish_activity(
        self,
        activity_id: str,
        *,
        success: bool,
        evidence_ids: list[str],
    ) -> ActivityRecord:
        async with self._state_lock:
            activity = await self._repository.finish_activity(
                activity_id,
                success=success,
                evidence_ids=evidence_ids,
            )
        await self._audit.append(
            action="activity.finished",
            actor_id="living-agent",
            outcome=activity.status.value,
            details={
                "activity_id": activity.activity_id,
                "evidence_ids": activity.evidence_ids,
            },
        )
        return activity

    async def activities(self, *, limit: int = 100) -> list[ActivityRecord]:
        return await self._repository.activities(limit=limit)

    async def activities_by_ids(self, activity_ids: list[str]) -> list[ActivityRecord]:
        return await self._repository.activities_by_ids(activity_ids)

    async def sources_match_conversation(
        self,
        source_event_ids: list[str],
        conversation_id: str | None,
    ) -> bool:
        events = await self._events.get_many(source_event_ids)
        return len(events) == len(source_event_ids) and all(
            event.conversation_id == conversation_id for event in events
        )

    async def _require_sources(self, source_event_ids: list[str]) -> None:
        events = await self._events.get_many(source_event_ids)
        if len(events) != len(source_event_ids):
            raise PsycheSourceError("all psyche records require existing source events")

    @staticmethod
    def _focus_summary(event: TrustedEvent) -> str:
        if isinstance(event.content, str):
            text = event.content
        else:
            text = str(event.content.get("text", event.event_type))
        normalized = " ".join(redact_text(text).split())[:180]
        return normalized or event.event_type
