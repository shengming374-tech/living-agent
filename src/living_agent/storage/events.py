"""Trusted event persistence repository."""

from __future__ import annotations

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
