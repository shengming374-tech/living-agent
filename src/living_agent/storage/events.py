"""Trusted event persistence repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from living_agent.models.events import TrustedEvent
from living_agent.storage.models import TrustedEventORM


class EventRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def add(self, event: TrustedEvent) -> None:
        content = event.content if isinstance(event.content, dict) else {"text": event.content}
        record = TrustedEventORM(
            event_id=event.event_id,
            event_type=event.event_type,
            content=content,
            source_type=event.source_type.value,
            source_identity=event.source_identity,
            conversation_id=event.conversation_id,
            trust_level=event.trust_level.value,
            authority_level=event.authority_level.value,
            taint_labels=sorted(event.taint_labels),
            created_at=event.created_at,
        )
        async with self._sessions() as session:
            session.add(record)
            await session.commit()

    async def get_many(self, event_ids: list[str]) -> list[TrustedEvent]:
        if not event_ids:
            return []
        statement = select(TrustedEventORM).where(TrustedEventORM.event_id.in_(event_ids))
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        by_id = {record.event_id: record for record in records}
        return [self._to_schema(by_id[event_id]) for event_id in event_ids if event_id in by_id]

    @staticmethod
    def _to_schema(record: TrustedEventORM) -> TrustedEvent:
        content: str | dict[str, object]
        if set(record.content) == {"text"} and isinstance(record.content["text"], str):
            content = record.content["text"]
        else:
            content = record.content
        return TrustedEvent(
            event_id=record.event_id,
            event_type=record.event_type,
            content=content,
            source_type=record.source_type,
            source_identity=record.source_identity,
            conversation_id=record.conversation_id,
            trust_level=record.trust_level,
            authority_level=record.authority_level,
            taint_labels=set(record.taint_labels),
            created_at=record.created_at,
        )
