"""Versioned memory persistence with scope-filtered reads."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from living_agent.memory.models import (
    MemoryCandidateORM,
    MemoryNodeORM,
    MemoryUsageORM,
    MemoryVersionORM,
)
from living_agent.models.memory import (
    CandidateStatus,
    MemoryCandidate,
    MemoryCandidateCreate,
    MemoryFactuality,
    MemoryMergeRequest,
    MemoryNode,
    MemorySplitRequest,
    MemoryStatus,
    MemoryUpdate,
    MemoryUsage,
    MemoryVersion,
)


class MemoryNotFoundError(LookupError):
    pass


class MemoryVersionConflictError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _pack_content(content: str | dict[str, Any]) -> dict[str, Any]:
    return content if isinstance(content, dict) else {"text": content}


def _unpack_content(content: dict[str, Any]) -> str | dict[str, Any]:
    if set(content) == {"text"} and isinstance(content["text"], str):
        return content["text"]
    return content


def _searchable_text(content: str | dict[str, Any]) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, sort_keys=True)


class MemoryRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create_candidate(
        self,
        candidate: MemoryCandidateCreate,
        *,
        proposer_id: str,
        source_trust: str,
    ) -> MemoryCandidate:
        now = _now()
        record = MemoryCandidateORM(
            candidate_id=candidate.candidate_id,
            proposer_id=proposer_id,
            memory_type=candidate.type.value,
            content=_pack_content(candidate.content),
            subject=candidate.subject,
            source_event_ids=candidate.source_event_ids,
            source_trust=source_trust,
            factuality=candidate.factuality.value,
            confidence=candidate.confidence,
            importance=candidate.importance,
            scope=candidate.scope,
            status=CandidateStatus.PENDING.value,
            decision_reason=None,
            created_at=now,
            updated_at=now,
        )
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
        return self._candidate_schema(record)

    async def get_candidate(self, candidate_id: str) -> MemoryCandidate:
        async with self._sessions() as session:
            record = await session.get(MemoryCandidateORM, candidate_id)
            if record is None:
                raise MemoryNotFoundError("memory candidate not found")
            return self._candidate_schema(record)

    async def candidate_exists(self, candidate_id: str) -> bool:
        async with self._sessions() as session:
            return await session.get(MemoryCandidateORM, candidate_id) is not None

    async def list_candidates(
        self,
        *,
        status: CandidateStatus | None,
        limit: int,
    ) -> list[MemoryCandidate]:
        statement = select(MemoryCandidateORM)
        if status is not None:
            statement = statement.where(MemoryCandidateORM.status == status.value)
        statement = statement.order_by(MemoryCandidateORM.updated_at.desc()).limit(limit)
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._candidate_schema(record) for record in records]

    async def reject_candidate(self, candidate_id: str, *, reason: str) -> MemoryCandidate:
        async with self._sessions() as session, session.begin():
            record = await session.get(MemoryCandidateORM, candidate_id)
            if record is None:
                raise MemoryNotFoundError("memory candidate not found")
            if record.status != CandidateStatus.PENDING.value:
                raise MemoryVersionConflictError("memory candidate is no longer pending")
            record.status = CandidateStatus.REJECTED.value
            record.decision_reason = reason
            record.updated_at = _now()
        return self._candidate_schema(record)

    async def has_conflict(self, candidate: MemoryCandidate) -> bool:
        statement = select(MemoryNodeORM.id).where(
            MemoryNodeORM.subject == candidate.subject,
            MemoryNodeORM.memory_type == candidate.type.value,
            MemoryNodeORM.scope == candidate.scope,
            MemoryNodeORM.status == MemoryStatus.ACTIVE.value,
            MemoryNodeORM.searchable_text != _searchable_text(candidate.content),
        )
        async with self._sessions() as session:
            return (await session.scalar(statement.limit(1))) is not None

    async def commit_candidate(
        self,
        candidate_id: str,
        *,
        factuality: MemoryFactuality,
        actor_id: str,
    ) -> tuple[MemoryCandidate, MemoryNode]:
        async with self._sessions() as session, session.begin():
            candidate = await session.get(MemoryCandidateORM, candidate_id)
            if candidate is None:
                raise MemoryNotFoundError("memory candidate not found")
            if candidate.status != CandidateStatus.PENDING.value:
                raise MemoryVersionConflictError("memory candidate is no longer pending")
            now = _now()
            node = MemoryNodeORM(
                id=str(uuid4()),
                memory_type=candidate.memory_type,
                content=candidate.content,
                searchable_text=_searchable_text(_unpack_content(candidate.content)),
                subject=candidate.subject,
                source_event_ids=candidate.source_event_ids,
                source_trust=candidate.source_trust,
                factuality=factuality.value,
                confidence=candidate.confidence,
                importance=candidate.importance,
                scope=candidate.scope,
                created_at=now,
                updated_at=now,
                status=MemoryStatus.ACTIVE.value,
                version=1,
            )
            session.add(node)
            session.add(self._version_record(node, actor_id=actor_id, change_type="created"))
            candidate.status = CandidateStatus.COMMITTED.value
            candidate.factuality = factuality.value
            candidate.decision_reason = "committed"
            candidate.updated_at = now
        return self._candidate_schema(candidate), self._node_schema(node)

    async def search(
        self,
        *,
        actor_id: str,
        conversation_id: str | None,
        owner: bool,
        query: str = "",
        include_deleted: bool = False,
        limit: int = 100,
    ) -> list[MemoryNode]:
        statement = select(MemoryNodeORM)
        if not owner:
            scopes = ["global", f"private:{actor_id}"]
            if conversation_id:
                scopes.append(f"conversation:{conversation_id}")
            statement = statement.where(MemoryNodeORM.scope.in_(scopes))
        if not include_deleted:
            statement = statement.where(MemoryNodeORM.status == MemoryStatus.ACTIVE.value)
        if query.strip():
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    MemoryNodeORM.searchable_text.ilike(pattern),
                    MemoryNodeORM.subject.ilike(pattern),
                )
            )
        statement = statement.order_by(MemoryNodeORM.updated_at.desc()).limit(limit)
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._node_schema(record) for record in records]

    async def get(self, memory_id: str) -> MemoryNode:
        async with self._sessions() as session:
            record = await session.get(MemoryNodeORM, memory_id)
            if record is None:
                raise MemoryNotFoundError("memory not found")
            return self._node_schema(record)

    async def update(
        self,
        memory_id: str,
        update: MemoryUpdate,
        *,
        actor_id: str,
    ) -> MemoryNode:
        async with self._sessions() as session, session.begin():
            record = await session.get(MemoryNodeORM, memory_id)
            if record is None:
                raise MemoryNotFoundError("memory not found")
            self._require_version(record, update.expected_version)
            changes = update.model_dump(exclude={"expected_version"}, exclude_unset=True)
            for field, value in changes.items():
                if field == "content":
                    record.content = _pack_content(value)
                    record.searchable_text = _searchable_text(value)
                elif field == "factuality":
                    record.factuality = value.value
                else:
                    setattr(record, field, value)
            self._advance(record)
            session.add(self._version_record(record, actor_id=actor_id, change_type="updated"))
        return self._node_schema(record)

    async def change_status(
        self,
        memory_id: str,
        *,
        expected_version: int,
        status: MemoryStatus,
        actor_id: str,
    ) -> MemoryNode:
        async with self._sessions() as session, session.begin():
            record = await session.get(MemoryNodeORM, memory_id)
            if record is None:
                raise MemoryNotFoundError("memory not found")
            self._require_version(record, expected_version)
            record.status = status.value
            self._advance(record)
            session.add(
                self._version_record(
                    record,
                    actor_id=actor_id,
                    change_type="deleted" if status is MemoryStatus.DELETED else "restored",
                )
            )
        return self._node_schema(record)

    async def versions(self, memory_id: str) -> list[MemoryVersion]:
        statement = (
            select(MemoryVersionORM)
            .where(MemoryVersionORM.memory_id == memory_id)
            .order_by(MemoryVersionORM.version)
        )
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        if not records:
            raise MemoryNotFoundError("memory versions not found")
        return [MemoryVersion.model_validate(record, from_attributes=True) for record in records]

    async def usages(self, memory_id: str) -> list[MemoryUsage]:
        statement = (
            select(MemoryUsageORM)
            .where(MemoryUsageORM.memory_id == memory_id)
            .order_by(MemoryUsageORM.created_at)
        )
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [MemoryUsage.model_validate(record, from_attributes=True) for record in records]

    async def record_usage(
        self,
        memory_id: str,
        *,
        response_id: str,
        conversation_id: str,
    ) -> MemoryUsage:
        await self.get(memory_id)
        record = MemoryUsageORM(
            usage_id=str(uuid4()),
            memory_id=memory_id,
            response_id=response_id,
            conversation_id=conversation_id,
            created_at=_now(),
        )
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
        return MemoryUsage.model_validate(record, from_attributes=True)

    async def merge(
        self,
        request: MemoryMergeRequest,
        *,
        actor_id: str,
    ) -> MemoryNode:
        async with self._sessions() as session, session.begin():
            records = [
                await session.get(MemoryNodeORM, memory_id) for memory_id in request.memory_ids
            ]
            if any(record is None for record in records):
                raise MemoryNotFoundError("merge source memory not found")
            sources = [record for record in records if record is not None]
            if any(record.status != MemoryStatus.ACTIVE.value for record in sources):
                raise MemoryVersionConflictError("merge sources must be active")
            source_event_ids = sorted(
                {event_id for record in sources for event_id in record.source_event_ids}
            )
            now = _now()
            merged = MemoryNodeORM(
                id=str(uuid4()),
                memory_type=request.type.value,
                content=_pack_content(request.content),
                searchable_text=_searchable_text(request.content),
                subject=request.subject,
                source_event_ids=source_event_ids,
                source_trust=self._least_trust(record.source_trust for record in sources),
                factuality=request.factuality.value,
                confidence=request.confidence,
                importance=request.importance,
                scope=request.scope,
                created_at=now,
                updated_at=now,
                status=MemoryStatus.ACTIVE.value,
                version=1,
            )
            session.add(merged)
            session.add(self._version_record(merged, actor_id=actor_id, change_type="merged"))
            for source in sources:
                source.status = MemoryStatus.DELETED.value
                self._advance(source)
                session.add(
                    self._version_record(source, actor_id=actor_id, change_type="merged_source")
                )
        return self._node_schema(merged)

    async def split(
        self,
        memory_id: str,
        request: MemorySplitRequest,
        *,
        actor_id: str,
    ) -> list[MemoryNode]:
        async with self._sessions() as session, session.begin():
            source = await session.get(MemoryNodeORM, memory_id)
            if source is None:
                raise MemoryNotFoundError("split source memory not found")
            if source.status != MemoryStatus.ACTIVE.value:
                raise MemoryVersionConflictError("split source must be active")
            source.status = MemoryStatus.DELETED.value
            self._advance(source)
            session.add(self._version_record(source, actor_id=actor_id, change_type="split_source"))
            now = _now()
            outputs: list[MemoryNodeORM] = []
            for part in request.parts:
                record = MemoryNodeORM(
                    id=str(uuid4()),
                    memory_type=part.type.value,
                    content=_pack_content(part.content),
                    searchable_text=_searchable_text(part.content),
                    subject=part.subject,
                    source_event_ids=source.source_event_ids,
                    source_trust=source.source_trust,
                    factuality=part.factuality.value,
                    confidence=part.confidence,
                    importance=part.importance,
                    scope=part.scope,
                    created_at=now,
                    updated_at=now,
                    status=MemoryStatus.ACTIVE.value,
                    version=1,
                )
                session.add(record)
                session.add(self._version_record(record, actor_id=actor_id, change_type="split"))
                outputs.append(record)
        return [self._node_schema(record) for record in outputs]

    @staticmethod
    def _advance(record: MemoryNodeORM) -> None:
        record.version += 1
        record.updated_at = _now()

    @staticmethod
    def _require_version(record: MemoryNodeORM, expected: int) -> None:
        if record.version != expected:
            raise MemoryVersionConflictError("memory version does not match")

    @classmethod
    def _version_record(
        cls,
        record: MemoryNodeORM,
        *,
        actor_id: str,
        change_type: str,
    ) -> MemoryVersionORM:
        return MemoryVersionORM(
            row_id=str(uuid4()),
            memory_id=record.id,
            version=record.version,
            snapshot=cls._node_schema(record).model_dump(mode="json"),
            change_type=change_type,
            actor_id=actor_id,
            created_at=_now(),
        )

    @staticmethod
    def _least_trust(values: Iterable[str]) -> str:
        ranking = {"untrusted": 0, "authenticated": 1, "trusted": 2}
        return min(values, key=lambda value: ranking.get(value, -1))

    @staticmethod
    def _candidate_schema(record: MemoryCandidateORM) -> MemoryCandidate:
        return MemoryCandidate(
            candidate_id=record.candidate_id,
            proposer_id=record.proposer_id,
            type=record.memory_type,
            content=_unpack_content(record.content),
            subject=record.subject,
            source_event_ids=record.source_event_ids,
            source_trust=record.source_trust,
            factuality=record.factuality,
            confidence=record.confidence,
            importance=record.importance,
            scope=record.scope,
            status=record.status,
            decision_reason=record.decision_reason,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _node_schema(record: MemoryNodeORM) -> MemoryNode:
        return MemoryNode(
            id=record.id,
            type=record.memory_type,
            content=_unpack_content(record.content),
            subject=record.subject,
            source_event_ids=record.source_event_ids,
            source_trust=record.source_trust,
            factuality=record.factuality,
            confidence=record.confidence,
            importance=record.importance,
            scope=record.scope,
            created_at=record.created_at,
            updated_at=record.updated_at,
            status=record.status,
            version=record.version,
        )
