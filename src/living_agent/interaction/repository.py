"""Persistence and atomic delivery operations for utterance Sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from living_agent.interaction.models import UtteranceSessionORM
from living_agent.models.conversation import UtteranceSession
from living_agent.models.events import AuthorityLevel, SourceType, TrustedEvent, TrustLevel
from living_agent.storage.models import TrustedEventORM


class DeliveryDisposition(StrEnum):
    RECORDED = "recorded"
    ALREADY_RECORDED = "already_recorded"
    OUT_OF_ORDER = "out_of_order"
    INTERRUPTED = "interrupted"
    UNIT_NOT_ISSUED = "unit_not_issued"
    SCOPE_MISMATCH = "scope_mismatch"
    SESSION_NOT_FOUND = "session_not_found"


@dataclass(frozen=True, slots=True)
class StoredUtterance:
    session: UtteranceSession
    platform: str
    conversation_id: str
    source_event_id: str
    recalled_memory_ids: tuple[str, ...]
    memory_trace_id: str | None
    attention_cue_id: str | None
    started_count: int
    generation: int
    replaced_session_id: str | None
    interruption_reason: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    disposition: DeliveryDisposition
    utterance: StoredUtterance | None
    event: TrustedEvent | None = None


def _now() -> datetime:
    return datetime.now(UTC)


class UtteranceRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(
        self,
        session_schema: UtteranceSession,
        *,
        platform: str,
        conversation_id: str,
        source_event_id: str,
        recalled_memory_ids: list[str],
        memory_trace_id: str | None,
        attention_cue_id: str | None,
        generation: int,
        replaced_session_id: str | None,
        started_count: int = 0,
        interruption_reason: str | None = None,
    ) -> StoredUtterance:
        now = _now()
        record = UtteranceSessionORM(
            session_id=session_schema.session_id,
            platform=platform,
            conversation_id=conversation_id,
            source_event_id=source_event_id,
            intention=session_schema.intention,
            units=[unit.model_dump(mode="json") for unit in session_schema.units],
            recalled_memory_ids=list(recalled_memory_ids),
            memory_trace_id=memory_trace_id,
            attention_cue_id=attention_cue_id,
            sent_count=session_schema.sent_count,
            started_count=started_count,
            interruption_policy=session_schema.interruption_policy,
            state=session_schema.state,
            generation=generation,
            replaced_session_id=replaced_session_id,
            interruption_reason=interruption_reason,
            created_at=now,
            updated_at=now,
        )
        async with self._sessions() as database_session:
            database_session.add(record)
            await database_session.commit()
        return self._to_schema(record)

    async def get(self, session_id: str) -> StoredUtterance | None:
        async with self._sessions() as database_session:
            record = await database_session.get(UtteranceSessionORM, session_id)
        return self._to_schema(record) if record is not None else None

    async def list_recoverable(self) -> list[StoredUtterance]:
        statement = (
            select(UtteranceSessionORM)
            .where(UtteranceSessionORM.state.in_(("planned", "sending")))
            .order_by(
                UtteranceSessionORM.platform,
                UtteranceSessionORM.conversation_id,
                UtteranceSessionORM.generation,
                UtteranceSessionORM.updated_at,
            )
        )
        async with self._sessions() as database_session:
            records = list((await database_session.scalars(statement)).all())
        return [self._to_schema(record) for record in records]

    async def generation_watermarks(self) -> dict[tuple[str, str], int]:
        statement = select(
            UtteranceSessionORM.platform,
            UtteranceSessionORM.conversation_id,
            func.max(UtteranceSessionORM.generation),
        ).group_by(UtteranceSessionORM.platform, UtteranceSessionORM.conversation_id)
        async with self._sessions() as database_session:
            rows = (await database_session.execute(statement)).all()
        return {
            (platform, conversation_id): generation
            for platform, conversation_id, generation in rows
        }

    async def mark_started(
        self,
        session_id: str,
        *,
        unit_index: int,
    ) -> StoredUtterance | None:
        async with self._sessions() as database_session, database_session.begin():
            record = await self._locked(database_session, session_id)
            if (
                record is None
                or record.state not in {"planned", "sending"}
                or record.started_count != unit_index
                or unit_index >= len(record.units)
            ):
                return None
            record.started_count += 1
            record.state = "sending"
            record.updated_at = _now()
        return self._to_schema(record)

    async def mark_cancelled(
        self,
        session_id: str,
        *,
        reason: str,
    ) -> StoredUtterance | None:
        async with self._sessions() as database_session, database_session.begin():
            record = await self._locked(database_session, session_id)
            if record is None:
                return None
            if record.state in {"planned", "sending"}:
                record.state = "cancelled"
                record.interruption_reason = reason
                record.updated_at = _now()
        return self._to_schema(record)

    async def record_delivery(
        self,
        session_id: str,
        *,
        platform: str,
        conversation_id: str,
        unit_index: int,
    ) -> DeliveryResult:
        async with self._sessions() as database_session, database_session.begin():
            record = await self._locked(database_session, session_id)
            if record is None:
                return DeliveryResult(DeliveryDisposition.SESSION_NOT_FOUND, None)
            if record.platform != platform or record.conversation_id != conversation_id:
                return DeliveryResult(
                    DeliveryDisposition.SCOPE_MISMATCH,
                    self._to_schema(record),
                )
            if unit_index < record.sent_count:
                return DeliveryResult(
                    DeliveryDisposition.ALREADY_RECORDED,
                    self._to_schema(record),
                )
            if unit_index >= len(record.units):
                return DeliveryResult(
                    DeliveryDisposition.UNIT_NOT_ISSUED,
                    self._to_schema(record),
                )
            started_before_cancellation = (
                record.state == "cancelled" and unit_index < record.started_count
            )
            if record.state == "cancelled" and not started_before_cancellation:
                return DeliveryResult(
                    DeliveryDisposition.INTERRUPTED,
                    self._to_schema(record),
                )
            if unit_index != record.sent_count:
                return DeliveryResult(
                    DeliveryDisposition.OUT_OF_ORDER,
                    self._to_schema(record),
                )
            if record.state == "completed":
                return DeliveryResult(
                    DeliveryDisposition.INTERRUPTED,
                    self._to_schema(record),
                )

            unit = record.units[unit_index]
            content = unit.get("text")
            if not isinstance(content, str) or not content:
                return DeliveryResult(
                    DeliveryDisposition.UNIT_NOT_ISSUED,
                    self._to_schema(record),
                )
            delivered = TrustedEvent(
                event_id=str(uuid4()),
                event_type="agent.response",
                content={
                    "text": content,
                    "reply_to_event_id": record.source_event_id,
                    "utterance_session_id": record.session_id,
                    "unit_index": unit_index,
                    "delivery_platform": platform,
                    "speech_function": unit.get("function"),
                },
                source_type=SourceType.AGENT_MESSAGE,
                source_identity="living-agent",
                conversation_id=conversation_id,
                trust_level=TrustLevel.TRUSTED,
                authority_level=AuthorityLevel.SYSTEM,
            )
            database_session.add(self._event_record(delivered))
            record.sent_count += 1
            record.started_count = max(record.started_count, record.sent_count)
            if record.state != "cancelled":
                record.state = "completed" if record.sent_count >= len(record.units) else "sending"
            record.updated_at = _now()
        return DeliveryResult(
            DeliveryDisposition.RECORDED,
            self._to_schema(record),
            delivered,
        )

    @staticmethod
    async def _locked(
        database_session: AsyncSession,
        session_id: str,
    ) -> UtteranceSessionORM | None:
        statement = (
            select(UtteranceSessionORM)
            .where(UtteranceSessionORM.session_id == session_id)
            .with_for_update()
        )
        record: UtteranceSessionORM | None = await database_session.scalar(statement)
        return record

    @staticmethod
    def _event_record(event: TrustedEvent) -> TrustedEventORM:
        assert isinstance(event.content, dict)
        return TrustedEventORM(
            event_id=event.event_id,
            event_type=event.event_type,
            content=event.content,
            source_type=event.source_type.value,
            source_identity=event.source_identity,
            conversation_id=event.conversation_id,
            trust_level=event.trust_level.value,
            authority_level=event.authority_level.value,
            taint_labels=sorted(event.taint_labels),
            created_at=event.created_at,
        )

    @staticmethod
    def _to_schema(record: UtteranceSessionORM) -> StoredUtterance:
        return StoredUtterance(
            session=UtteranceSession.model_validate(
                {
                    "session_id": record.session_id,
                    "intention": record.intention,
                    "units": record.units,
                    "sent_count": record.sent_count,
                    "interruption_policy": record.interruption_policy,
                    "state": record.state,
                }
            ),
            platform=record.platform,
            conversation_id=record.conversation_id,
            source_event_id=record.source_event_id,
            recalled_memory_ids=tuple(record.recalled_memory_ids),
            memory_trace_id=record.memory_trace_id,
            attention_cue_id=record.attention_cue_id,
            started_count=record.started_count,
            generation=record.generation,
            replaced_session_id=record.replaced_session_id,
            interruption_reason=record.interruption_reason,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
