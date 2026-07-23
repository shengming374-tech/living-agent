"""Durable state for conversation scheduling, focus, and sourced associations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from living_agent.interaction.models import (
    AttentionCueORM,
    ConversationRuntimeStateORM,
    SessionImpressionORM,
)
from living_agent.models.conversation import (
    AttentionCue,
    ConversationRuntimeState,
    SessionImpression,
    TurnScheduleDecision,
)
from living_agent.models.events import SourceType, TrustedEvent


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class SocialStateRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def observe(self, event: TrustedEvent) -> ConversationRuntimeState | None:
        conversation_id = event.conversation_id
        if conversation_id is None or event.source_type not in {
            SourceType.DIRECT_MESSAGE,
            SourceType.GROUP_MESSAGE,
        }:
            return None
        now = _aware(event.created_at)
        forced = event.source_type is SourceType.DIRECT_MESSAGE or (
            isinstance(event.content, dict) and bool(event.content.get("mentions_agent", False))
        )
        async with self._sessions() as session, session.begin():
            record = await session.get(ConversationRuntimeStateORM, conversation_id)
            if record is None:
                record = ConversationRuntimeStateORM(
                    conversation_id=conversation_id,
                    pending_event_ids=[event.event_id],
                    focus_salience=0.9 if forced else 0.25,
                    is_focused=False,
                    forced_wakeup=forced,
                    consecutive_idle_count=0,
                    cooldown_until=None,
                    next_evaluation_at=None,
                    last_external_at=now,
                    last_agent_at=None,
                    updated_at=now,
                    version=1,
                )
                session.add(record)
            else:
                record.pending_event_ids = [*record.pending_event_ids, event.event_id][-32:]
                record.focus_salience = min(
                    1.0,
                    max(record.focus_salience, 0.9 if forced else 0.25)
                    + (0.05 if not forced else 0.0),
                )
                record.forced_wakeup = record.forced_wakeup or forced
                record.last_external_at = now
                record.updated_at = now
                record.version += 1
        return self._state(record)

    async def get(self, conversation_id: str) -> ConversationRuntimeState | None:
        async with self._sessions() as session:
            record = await session.get(ConversationRuntimeStateORM, conversation_id)
        return self._state(record) if record is not None else None

    async def resolve(
        self,
        conversation_id: str,
        decision: TurnScheduleDecision,
        *,
        now: datetime,
        idle_exit_cycles: int,
    ) -> ConversationRuntimeState:
        target = _aware(now)
        async with self._sessions() as session, session.begin():
            record = await session.get(ConversationRuntimeStateORM, conversation_id)
            if record is None:
                raise LookupError("conversation runtime state not found")
            consumed = set(decision.pending_event_ids)
            if decision.action in {"trigger", "suppress"}:
                record.pending_event_ids = [
                    event_id for event_id in record.pending_event_ids if event_id not in consumed
                ]
            if decision.action == "trigger":
                await session.execute(
                    update(ConversationRuntimeStateORM)
                    .where(ConversationRuntimeStateORM.conversation_id != conversation_id)
                    .where(ConversationRuntimeStateORM.is_focused.is_(True))
                    .values(
                        is_focused=False,
                        forced_wakeup=False,
                        updated_at=target,
                        version=ConversationRuntimeStateORM.version + 1,
                    )
                )
                record.is_focused = True
                record.focus_salience = max(record.focus_salience, decision.score)
                record.forced_wakeup = False
                record.consecutive_idle_count = 0
                record.next_evaluation_at = None
            else:
                record.consecutive_idle_count += 1
                record.next_evaluation_at = (
                    target.replace(microsecond=0) if decision.action == "wait" else None
                )
                if decision.delay_seconds is not None:
                    record.next_evaluation_at = target + timedelta(seconds=decision.delay_seconds)
                if record.consecutive_idle_count >= idle_exit_cycles:
                    record.is_focused = False
                    record.focus_salience *= 0.5
                    record.forced_wakeup = False
            record.updated_at = target
            record.version += 1
        return self._state(record)

    async def mark_agent_spoke(
        self,
        conversation_id: str,
        *,
        now: datetime,
        cooldown_seconds: float,
    ) -> ConversationRuntimeState | None:
        target = _aware(now)
        async with self._sessions() as session, session.begin():
            record = await session.get(ConversationRuntimeStateORM, conversation_id)
            if record is None:
                return None
            record.last_agent_at = target
            record.cooldown_until = target + timedelta(seconds=cooldown_seconds)
            record.focus_salience = max(0.1, record.focus_salience * 0.8)
            record.updated_at = target
            record.version += 1
        return self._state(record)

    async def latest_impression(
        self,
        conversation_id: str,
        *,
        now: datetime,
    ) -> SessionImpression | None:
        statement = (
            select(SessionImpressionORM)
            .where(SessionImpressionORM.conversation_id == conversation_id)
            .where(SessionImpressionORM.expires_at > _aware(now))
            .order_by(SessionImpressionORM.created_at.desc())
            .limit(1)
        )
        async with self._sessions() as session:
            record = await session.scalar(statement)
        return self._impression(record) if record is not None else None

    async def save_impression(self, impression: SessionImpression) -> SessionImpression:
        record = SessionImpressionORM(**impression.model_dump())
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
        return self._impression(record)

    async def latest_cue(
        self,
        conversation_id: str,
        *,
        now: datetime,
        include_used: bool = False,
    ) -> AttentionCue | None:
        statement = (
            select(AttentionCueORM)
            .where(AttentionCueORM.conversation_id == conversation_id)
            .where(AttentionCueORM.expires_at > _aware(now))
        )
        if not include_used:
            statement = statement.where(AttentionCueORM.used.is_(False))
        statement = statement.order_by(AttentionCueORM.created_at.desc()).limit(1)
        async with self._sessions() as session:
            record = await session.scalar(statement)
        return self._cue(record) if record is not None else None

    async def save_cue(self, cue: AttentionCue) -> AttentionCue:
        record = AttentionCueORM(**cue.model_dump())
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
        return self._cue(record)

    async def mark_cue_used(self, cue_id: str) -> AttentionCue | None:
        async with self._sessions() as session, session.begin():
            record = await session.get(AttentionCueORM, cue_id)
            if record is None:
                return None
            record.used = True
        return self._cue(record)

    @staticmethod
    def _state(record: ConversationRuntimeStateORM) -> ConversationRuntimeState:
        return ConversationRuntimeState.model_validate(record, from_attributes=True)

    @staticmethod
    def _impression(record: SessionImpressionORM) -> SessionImpression:
        return SessionImpression.model_validate(record, from_attributes=True)

    @staticmethod
    def _cue(record: AttentionCueORM) -> AttentionCue:
        return AttentionCue.model_validate(record, from_attributes=True)
