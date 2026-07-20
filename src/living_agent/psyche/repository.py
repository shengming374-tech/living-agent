"""Persistence operations for continuous psyche state and evidence records."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from living_agent.models.psyche import (
    ActivityRecord,
    ActivityStatus,
    PsycheState,
    PsycheStateUpdate,
    ThoughtRecord,
    ThoughtRecordCreate,
    TopicStatus,
    UnresolvedTopic,
    UnresolvedTopicCreate,
)
from living_agent.psyche.models import (
    ActivityRecordORM,
    PsycheStateORM,
    ThoughtRecordORM,
    UnresolvedTopicORM,
)

PRIMARY_STATE_ID = "primary"


class PsycheNotFoundError(LookupError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class PsycheRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def initialize(self) -> PsycheState:
        async with self._sessions() as session:
            record = await session.get(PsycheStateORM, PRIMARY_STATE_ID)
            if record is None:
                now = _now()
                record = PsycheStateORM(
                    state_id=PRIMARY_STATE_ID,
                    valence=0.0,
                    arousal=0.0,
                    current_focus=None,
                    focus_salience=0.0,
                    unresolved_topic_ids=[],
                    current_activity_id=None,
                    last_decay_at=now,
                    updated_at=now,
                    version=1,
                )
                session.add(record)
                await session.commit()
        return self._state(record)

    async def state(self) -> PsycheState:
        async with self._sessions() as session:
            record = await session.get(PsycheStateORM, PRIMARY_STATE_ID)
        if record is None:
            raise PsycheNotFoundError("psyche state is not initialized")
        return self._state(record)

    async def update_state(self, update: PsycheStateUpdate) -> PsycheState:
        async with self._sessions() as session, session.begin():
            record = await session.get(PsycheStateORM, PRIMARY_STATE_ID)
            if record is None:
                raise PsycheNotFoundError("psyche state is not initialized")
            changes = update.model_dump(exclude_unset=True)
            for field, value in changes.items():
                setattr(record, field, value)
            self._advance(record)
        return self._state(record)

    async def apply_decay(self, *, now: datetime, half_life_hours: float) -> PsycheState:
        async with self._sessions() as session, session.begin():
            record = await session.get(PsycheStateORM, PRIMARY_STATE_ID)
            if record is None:
                raise PsycheNotFoundError("psyche state is not initialized")
            target = _aware(now)
            elapsed_hours = max(
                0.0,
                (target - _aware(record.last_decay_at)).total_seconds() / 3600,
            )
            factor = math.pow(0.5, elapsed_hours / half_life_hours)
            record.valence *= factor
            record.arousal *= factor
            record.focus_salience *= factor
            if record.focus_salience < 0.05:
                record.current_focus = None
                record.focus_salience = 0.0
            record.last_decay_at = target
            self._advance(record, now=target)
        return self._state(record)

    async def create_thought(self, create: ThoughtRecordCreate) -> ThoughtRecord:
        record = ThoughtRecordORM(
            thought_id=str(uuid4()),
            kind=create.kind,
            summary=create.summary,
            source_event_ids=create.source_event_ids,
            intensity=create.intensity,
            speakability=create.speakability,
            created_at=_now(),
            expires_at=create.expires_at,
            resolved=False,
        )
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
        return self._thought(record)

    async def thoughts(
        self,
        *,
        include_resolved: bool = False,
        limit: int = 100,
    ) -> list[ThoughtRecord]:
        statement = select(ThoughtRecordORM)
        if not include_resolved:
            statement = statement.where(ThoughtRecordORM.resolved.is_(False))
        statement = statement.order_by(ThoughtRecordORM.created_at.desc()).limit(limit)
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._thought(record) for record in records]

    async def thoughts_by_ids(self, thought_ids: list[str]) -> list[ThoughtRecord]:
        if not thought_ids:
            return []
        statement = select(ThoughtRecordORM).where(ThoughtRecordORM.thought_id.in_(thought_ids))
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        by_id = {record.thought_id: record for record in records}
        return [self._thought(by_id[item]) for item in thought_ids if item in by_id]

    async def resolve_thought(self, thought_id: str) -> ThoughtRecord:
        async with self._sessions() as session, session.begin():
            record = await session.get(ThoughtRecordORM, thought_id)
            if record is None:
                raise PsycheNotFoundError("thought record not found")
            record.resolved = True
        return self._thought(record)

    async def create_topic(self, create: UnresolvedTopicCreate) -> UnresolvedTopic:
        record = UnresolvedTopicORM(
            topic_id=str(uuid4()),
            summary=create.summary,
            source_event_ids=create.source_event_ids,
            status=TopicStatus.OPEN.value,
            created_at=_now(),
            resolved_at=None,
        )
        async with self._sessions() as session, session.begin():
            state = await session.get(PsycheStateORM, PRIMARY_STATE_ID)
            if state is None:
                raise PsycheNotFoundError("psyche state is not initialized")
            session.add(record)
            state.unresolved_topic_ids = [*state.unresolved_topic_ids, record.topic_id]
            self._advance(state)
        return self._topic(record)

    async def topics(self, *, include_resolved: bool = False) -> list[UnresolvedTopic]:
        statement = select(UnresolvedTopicORM)
        if not include_resolved:
            statement = statement.where(UnresolvedTopicORM.status == TopicStatus.OPEN.value)
        statement = statement.order_by(UnresolvedTopicORM.created_at)
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._topic(record) for record in records]

    async def resolve_topic(self, topic_id: str) -> UnresolvedTopic:
        async with self._sessions() as session, session.begin():
            record = await session.get(UnresolvedTopicORM, topic_id)
            state = await session.get(PsycheStateORM, PRIMARY_STATE_ID)
            if record is None or state is None:
                raise PsycheNotFoundError("psyche topic or state not found")
            record.status = TopicStatus.RESOLVED.value
            record.resolved_at = _now()
            state.unresolved_topic_ids = [
                item for item in state.unresolved_topic_ids if item != topic_id
            ]
            self._advance(state)
        return self._topic(record)

    async def start_activity(
        self,
        *,
        kind: str,
        summary: str,
        source_event_ids: list[str],
    ) -> ActivityRecord:
        record = ActivityRecordORM(
            activity_id=str(uuid4()),
            kind=kind,
            summary=summary,
            source_event_ids=source_event_ids,
            status=ActivityStatus.RUNNING.value,
            evidence_ids=[],
            started_at=_now(),
            finished_at=None,
        )
        async with self._sessions() as session, session.begin():
            state = await session.get(PsycheStateORM, PRIMARY_STATE_ID)
            if state is None:
                raise PsycheNotFoundError("psyche state is not initialized")
            session.add(record)
            state.current_activity_id = record.activity_id
            self._advance(state)
        return self._activity(record)

    async def finish_activity(
        self,
        activity_id: str,
        *,
        success: bool,
        evidence_ids: list[str],
    ) -> ActivityRecord:
        async with self._sessions() as session, session.begin():
            record = await session.get(ActivityRecordORM, activity_id)
            state = await session.get(PsycheStateORM, PRIMARY_STATE_ID)
            if record is None or state is None:
                raise PsycheNotFoundError("activity or psyche state not found")
            record.status = (
                ActivityStatus.COMPLETED.value if success else ActivityStatus.FAILED.value
            )
            record.evidence_ids = evidence_ids
            record.finished_at = _now()
            if state.current_activity_id == activity_id:
                state.current_activity_id = None
                self._advance(state)
        return self._activity(record)

    async def activities(self, *, limit: int = 100) -> list[ActivityRecord]:
        statement = (
            select(ActivityRecordORM).order_by(ActivityRecordORM.started_at.desc()).limit(limit)
        )
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._activity(record) for record in records]

    async def activities_by_ids(self, activity_ids: list[str]) -> list[ActivityRecord]:
        if not activity_ids:
            return []
        statement = select(ActivityRecordORM).where(ActivityRecordORM.activity_id.in_(activity_ids))
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        by_id = {record.activity_id: record for record in records}
        return [self._activity(by_id[item]) for item in activity_ids if item in by_id]

    @staticmethod
    def _advance(record: PsycheStateORM, *, now: datetime | None = None) -> None:
        record.version += 1
        record.updated_at = now or _now()

    @staticmethod
    def _state(record: PsycheStateORM) -> PsycheState:
        return PsycheState.model_validate(record, from_attributes=True)

    @staticmethod
    def _thought(record: ThoughtRecordORM) -> ThoughtRecord:
        return ThoughtRecord.model_validate(record, from_attributes=True)

    @staticmethod
    def _topic(record: UnresolvedTopicORM) -> UnresolvedTopic:
        return UnresolvedTopic.model_validate(record, from_attributes=True)

    @staticmethod
    def _activity(record: ActivityRecordORM) -> ActivityRecord:
        return ActivityRecord.model_validate(record, from_attributes=True)
