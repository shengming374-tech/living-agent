"""Trusted event persistence repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from living_agent.models.events import AuthorityLevel, SourceType, TrustedEvent, TrustLevel
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

    async def recent_for_conversation(
        self,
        conversation_id: str,
        *,
        limit: int = 8,
        exclude_event_id: str | None = None,
    ) -> list[TrustedEvent]:
        statement = (
            select(TrustedEventORM)
            .where(TrustedEventORM.conversation_id == conversation_id)
            .order_by(TrustedEventORM.created_at.desc())
            .limit(limit + (1 if exclude_event_id else 0))
        )
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        if exclude_event_id is not None:
            records = [record for record in records if record.event_id != exclude_event_id]
        records.reverse()
        return [self._to_schema(record) for record in records[:limit]]

    async def add_agent_message(
        self,
        *,
        conversation_id: str,
        content: str,
        source_event_id: str,
        utterance_session_id: str | None = None,
        unit_index: int | None = None,
        delivery_platform: str | None = None,
    ) -> TrustedEvent:
        event = TrustedEvent(
            event_type="agent.response",
            content={
                "text": content,
                "reply_to_event_id": source_event_id,
                "utterance_session_id": utterance_session_id,
                "unit_index": unit_index,
                "delivery_platform": delivery_platform,
            },
            source_type=SourceType.AGENT_MESSAGE,
            source_identity="living-agent",
            conversation_id=conversation_id,
            trust_level=TrustLevel.TRUSTED,
            authority_level=AuthorityLevel.SYSTEM,
        )
        await self.add(event)
        return event

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
