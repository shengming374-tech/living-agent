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
    MemoryRecallTraceItemORM,
    MemoryRecallTraceORM,
    MemoryUsageORM,
    MemoryVersionORM,
)
from living_agent.models.memory import (
    CandidateStatus,
    MemoryCandidate,
    MemoryCandidateCreate,
    MemoryFactuality,
    MemoryLayer,
    MemoryMergeRequest,
    MemoryNode,
    MemoryRecallTrace,
    MemoryRecallTraceBundle,
    MemoryRecallTraceCreate,
    MemoryRecallTraceItem,
    MemoryRecallTraceItemCreate,
    MemorySplitRequest,
    MemoryStatus,
    MemorySupportMode,
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
            memory_layer=(
                candidate.memory_layer.value if candidate.memory_layer is not None else None
            ),
            entity_id=candidate.entity_id,
            memory_key=candidate.memory_key,
            valid_until=candidate.valid_until,
            superseded_by_id=candidate.superseded_by_id,
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

    async def defer_candidate(self, candidate_id: str, *, reason: str) -> MemoryCandidate:
        async with self._sessions() as session, session.begin():
            record = await session.get(MemoryCandidateORM, candidate_id)
            if record is None:
                raise MemoryNotFoundError("memory candidate not found")
            if record.status != CandidateStatus.PENDING.value:
                raise MemoryVersionConflictError("memory candidate is no longer pending")
            record.decision_reason = reason
            record.updated_at = _now()
        return self._candidate_schema(record)

    async def equivalent_memory(self, candidate: MemoryCandidate) -> MemoryNode | None:
        statement = select(MemoryNodeORM).where(
            MemoryNodeORM.subject == candidate.subject,
            MemoryNodeORM.memory_type == candidate.type.value,
            MemoryNodeORM.scope == candidate.scope,
            MemoryNodeORM.status == MemoryStatus.ACTIVE.value,
            MemoryNodeORM.searchable_text == _searchable_text(candidate.content),
        )
        async with self._sessions() as session:
            record = await session.scalar(statement.limit(1))
        return self._node_schema(record) if record is not None else None

    async def equivalent_pending_candidate(
        self,
        candidate: MemoryCandidate,
    ) -> MemoryCandidate | None:
        statement = (
            select(MemoryCandidateORM)
            .where(
                MemoryCandidateORM.candidate_id != candidate.candidate_id,
                MemoryCandidateORM.proposer_id == candidate.proposer_id,
                MemoryCandidateORM.memory_type == candidate.type.value,
                MemoryCandidateORM.subject == candidate.subject,
                MemoryCandidateORM.scope == candidate.scope,
                MemoryCandidateORM.status == CandidateStatus.PENDING.value,
            )
            .order_by(MemoryCandidateORM.updated_at.desc())
        )
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        for record in records:
            pending = self._candidate_schema(record)
            if (
                pending.content == candidate.content
                and pending.source_event_ids == candidate.source_event_ids
                and pending.factuality == candidate.factuality
                and pending.confidence == candidate.confidence
                and pending.importance == candidate.importance
            ):
                return pending
        return None

    async def conflicts(self, candidate: MemoryCandidate) -> list[MemoryNode]:
        statement = select(MemoryNodeORM).where(
            MemoryNodeORM.subject == candidate.subject,
            MemoryNodeORM.memory_type == candidate.type.value,
            MemoryNodeORM.scope == candidate.scope,
            MemoryNodeORM.status == MemoryStatus.ACTIVE.value,
            MemoryNodeORM.searchable_text != _searchable_text(candidate.content),
        )
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._node_schema(record) for record in records]

    async def has_conflict(self, candidate: MemoryCandidate) -> bool:
        return bool(await self.conflicts(candidate))

    async def commit_candidate(
        self,
        candidate_id: str,
        *,
        factuality: MemoryFactuality,
        actor_id: str,
        supersede_memory_ids: list[str] | None = None,
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
                memory_layer=candidate.memory_layer,
                entity_id=candidate.entity_id,
                memory_key=candidate.memory_key,
                valid_until=candidate.valid_until,
                superseded_by_id=candidate.superseded_by_id,
                created_at=now,
                updated_at=now,
                status=MemoryStatus.ACTIVE.value,
                version=1,
            )
            session.add(node)
            session.add(self._version_record(node, actor_id=actor_id, change_type="created"))
            superseded_ids = supersede_memory_ids or []
            if superseded_ids:
                records = list(
                    (
                        await session.scalars(
                            select(MemoryNodeORM).where(
                                MemoryNodeORM.id.in_(superseded_ids)
                            )
                        )
                    ).all()
                )
                if len(records) != len(set(superseded_ids)):
                    raise MemoryNotFoundError("superseded memory not found")
                for source in records:
                    if source.status != MemoryStatus.ACTIVE.value:
                        raise MemoryVersionConflictError(
                            "superseded memory must still be active"
                        )
                    source.status = MemoryStatus.DELETED.value
                    source.superseded_by_id = node.id
                    self._advance(source)
                    session.add(
                        self._version_record(
                            source,
                            actor_id=actor_id,
                            change_type="superseded",
                        )
                    )
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
            statement = statement.where(
                MemoryNodeORM.scope.in_(
                    self._accessible_scopes(
                        actor_id=actor_id,
                        conversation_id=conversation_id,
                    )
                )
            )
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

    async def exact_fact(
        self,
        *,
        entity_id: str,
        memory_key: str,
        actor_id: str,
        conversation_id: str | None,
        owner: bool,
    ) -> MemoryNode | None:
        statement = select(MemoryNodeORM).where(
            MemoryNodeORM.memory_layer == MemoryLayer.FACT.value,
            MemoryNodeORM.entity_id == entity_id,
            MemoryNodeORM.memory_key == memory_key,
            MemoryNodeORM.status == MemoryStatus.ACTIVE.value,
        )
        if not owner:
            statement = statement.where(
                MemoryNodeORM.scope.in_(
                    self._accessible_scopes(
                        actor_id=actor_id,
                        conversation_id=conversation_id,
                    )
                )
            )
        statement = statement.order_by(MemoryNodeORM.updated_at.desc()).limit(1)
        async with self._sessions() as session:
            record = await session.scalar(statement)
        return self._node_schema(record) if record is not None else None

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
            if status is MemoryStatus.ACTIVE and record.status != MemoryStatus.ACTIVE.value:
                active_sibling = await session.scalar(
                    select(MemoryNodeORM.id)
                    .where(
                        MemoryNodeORM.id != record.id,
                        MemoryNodeORM.subject == record.subject,
                        MemoryNodeORM.memory_type == record.memory_type,
                        MemoryNodeORM.scope == record.scope,
                        MemoryNodeORM.status == MemoryStatus.ACTIVE.value,
                    )
                    .limit(1)
                )
                if active_sibling is not None:
                    raise MemoryVersionConflictError(
                        "an active memory with the same subject and scope already exists"
                    )
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

    async def create_recall_trace(
        self,
        trace: MemoryRecallTraceCreate,
        items: list[MemoryRecallTraceItemCreate],
    ) -> MemoryRecallTraceBundle:
        if any(item.trace_id != trace.trace_id for item in items):
            raise ValueError("recall trace items must reference the created trace")
        memory_ids = [item.memory_id for item in items]
        if len(memory_ids) != len(set(memory_ids)):
            raise ValueError("recall trace memory IDs must be unique")

        now = _now()
        trace_record = MemoryRecallTraceORM(
            trace_id=trace.trace_id,
            event_id=trace.event_id,
            response_id=trace.response_id,
            conversation_id=trace.conversation_id,
            actor_id=trace.actor_id,
            route=trace.route,
            query_hash=trace.query_hash,
            context_fingerprint=trace.context_fingerprint,
            support_mode=trace.support_mode.value,
            created_at=now,
            updated_at=now,
        )
        item_records = [
            MemoryRecallTraceItemORM(
                row_id=item.row_id,
                trace_id=item.trace_id,
                memory_id=item.memory_id,
                memory_layer=item.memory_layer.value,
                selection_reason=item.selection_reason,
                lexical_score=item.lexical_score,
                semantic_score=item.semantic_score,
                final_score=item.final_score,
                selected=item.selected,
                injected=item.injected,
                response_match=item.response_match,
                source_overlap=item.source_overlap,
                created_at=now,
                updated_at=now,
            )
            for item in items
        ]
        async with self._sessions() as session, session.begin():
            session.add(trace_record)
            session.add_all(item_records)
        return MemoryRecallTraceBundle(
            trace=self._trace_schema(trace_record),
            items=[self._trace_item_schema(item) for item in item_records],
        )

    async def get_recall_trace(self, trace_id: str) -> MemoryRecallTraceBundle:
        async with self._sessions() as session:
            trace = await session.get(MemoryRecallTraceORM, trace_id)
            if trace is None:
                raise MemoryNotFoundError("memory recall trace not found")
            statement = (
                select(MemoryRecallTraceItemORM)
                .where(MemoryRecallTraceItemORM.trace_id == trace_id)
                .order_by(
                    MemoryRecallTraceItemORM.created_at,
                    MemoryRecallTraceItemORM.row_id,
                )
            )
            items = list((await session.scalars(statement)).all())
        return MemoryRecallTraceBundle(
            trace=self._trace_schema(trace),
            items=[self._trace_item_schema(item) for item in items],
        )

    async def list_recall_traces(self, *, limit: int) -> list[MemoryRecallTrace]:
        if limit < 1:
            raise ValueError("recall trace limit must be positive")
        statement = (
            select(MemoryRecallTraceORM)
            .order_by(
                MemoryRecallTraceORM.created_at.desc(),
                MemoryRecallTraceORM.trace_id.desc(),
            )
            .limit(limit)
        )
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._trace_schema(record) for record in records]

    async def complete_recall_trace(
        self,
        trace_id: str,
        *,
        response_id: str | None = None,
        context_fingerprint: str | None = None,
        support_mode: MemorySupportMode | None = None,
        item_updates: dict[str, dict[str, bool | None]] | None = None,
    ) -> MemoryRecallTraceBundle:
        allowed_item_fields = {"response_match", "source_overlap", "injected"}
        updates = item_updates or {}
        async with self._sessions() as session, session.begin():
            trace = await session.get(MemoryRecallTraceORM, trace_id)
            if trace is None:
                raise MemoryNotFoundError("memory recall trace not found")
            statement = (
                select(MemoryRecallTraceItemORM)
                .where(MemoryRecallTraceItemORM.trace_id == trace_id)
                .order_by(
                    MemoryRecallTraceItemORM.created_at,
                    MemoryRecallTraceItemORM.row_id,
                )
            )
            items = list((await session.scalars(statement)).all())
            by_memory_id = {item.memory_id: item for item in items}
            missing = set(updates) - set(by_memory_id)
            if missing:
                raise MemoryNotFoundError("memory recall trace item not found")

            now = _now()
            for memory_id, update in updates.items():
                unexpected = set(update) - allowed_item_fields
                if unexpected:
                    raise ValueError("unsupported recall trace item update")
                item = by_memory_id[memory_id]
                if "response_match" in update:
                    response_match = update["response_match"]
                    if response_match is not None and not isinstance(response_match, bool):
                        raise ValueError("response_match must be boolean or null")
                    item.response_match = response_match
                for field in ("source_overlap", "injected"):
                    if field not in update:
                        continue
                    value = update[field]
                    if not isinstance(value, bool):
                        raise ValueError(f"{field} must be boolean")
                    setattr(item, field, value)
                if update:
                    item.updated_at = now

            if response_id is not None:
                trace.response_id = response_id
            if context_fingerprint is not None:
                trace.context_fingerprint = context_fingerprint
            if support_mode is not None:
                trace.support_mode = support_mode.value
            trace.updated_at = now
        return MemoryRecallTraceBundle(
            trace=self._trace_schema(trace),
            items=[self._trace_item_schema(item) for item in items],
        )

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
                memory_layer=MemoryLayer.NARRATIVE.value,
                entity_id=None,
                memory_key=None,
                valid_until=None,
                superseded_by_id=None,
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
                    memory_layer=MemoryLayer.NARRATIVE.value,
                    entity_id=None,
                    memory_key=None,
                    valid_until=None,
                    superseded_by_id=None,
                    created_at=now,
                    updated_at=now,
                    status=MemoryStatus.ACTIVE.value,
                    version=1,
                )
                session.add(record)
                session.add(self._version_record(record, actor_id=actor_id, change_type="split"))
                outputs.append(record)
        return [self._node_schema(record) for record in outputs]

    async def normalize_fact(
        self,
        memory_id: str,
        structured_content: dict[str, Any],
        entity_id: str,
        memory_key: str,
        actor_id: str,
    ) -> MemoryNode:
        packed_content = _pack_content(structured_content)
        searchable_text = _searchable_text(structured_content)
        async with self._sessions() as session, session.begin():
            record = await session.get(MemoryNodeORM, memory_id)
            if record is None:
                raise MemoryNotFoundError("memory not found")
            if (
                record.content == packed_content
                and record.searchable_text == searchable_text
                and record.memory_layer == MemoryLayer.FACT.value
                and record.entity_id == entity_id
                and record.memory_key == memory_key
            ):
                return self._node_schema(record)

            record.content = packed_content
            record.searchable_text = searchable_text
            record.memory_layer = MemoryLayer.FACT.value
            record.entity_id = entity_id
            record.memory_key = memory_key
            self._advance(record)
            session.add(
                self._version_record(
                    record,
                    actor_id=actor_id,
                    change_type="migrated",
                )
            )
        return self._node_schema(record)

    async def apply_existing_fact(
        self,
        candidate_id: str,
        actor_id: str,
        correction: bool,
    ) -> tuple[MemoryCandidate, MemoryNode, str] | None:
        async with self._sessions() as session, session.begin():
            candidate = await session.get(MemoryCandidateORM, candidate_id)
            if candidate is None:
                raise MemoryNotFoundError("memory candidate not found")
            if (
                candidate.status != CandidateStatus.PENDING.value
                or candidate.memory_layer != MemoryLayer.FACT.value
                or candidate.entity_id is None
                or candidate.memory_key is None
            ):
                return None

            statement = (
                select(MemoryNodeORM)
                .where(
                    MemoryNodeORM.memory_layer == MemoryLayer.FACT.value,
                    MemoryNodeORM.entity_id == candidate.entity_id,
                    MemoryNodeORM.memory_key == candidate.memory_key,
                    MemoryNodeORM.scope == candidate.scope,
                    MemoryNodeORM.status == MemoryStatus.ACTIVE.value,
                )
                .order_by(MemoryNodeORM.updated_at.desc())
                .limit(1)
            )
            node = await session.scalar(statement)
            if node is None:
                return None

            same_content = node.content == candidate.content
            if not same_content and not correction:
                return None

            node.source_event_ids = list(
                dict.fromkeys([*node.source_event_ids, *candidate.source_event_ids])
            )
            if same_content:
                change_type = "confirmed"
                node.confidence = min(
                    0.98,
                    max(node.confidence, candidate.confidence) + 0.05,
                )
            else:
                change_type = "corrected"
                node.content = candidate.content
                node.searchable_text = _searchable_text(
                    _unpack_content(candidate.content)
                )
                node.confidence = candidate.confidence

            self._advance(node)
            session.add(
                self._version_record(
                    node,
                    actor_id=actor_id,
                    change_type=change_type,
                )
            )
            candidate.status = CandidateStatus.COMMITTED.value
            candidate.decision_reason = change_type
            candidate.updated_at = node.updated_at
        return self._candidate_schema(candidate), self._node_schema(node), change_type

    @staticmethod
    def _accessible_scopes(
        *,
        actor_id: str,
        conversation_id: str | None,
    ) -> list[str]:
        scopes = ["global", f"private:{actor_id}"]
        if conversation_id:
            scopes.append(f"conversation:{conversation_id}")
        return scopes

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
            memory_layer=record.memory_layer,
            entity_id=record.entity_id,
            memory_key=record.memory_key,
            valid_until=record.valid_until,
            superseded_by_id=record.superseded_by_id,
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
            memory_layer=record.memory_layer,
            entity_id=record.entity_id,
            memory_key=record.memory_key,
            valid_until=record.valid_until,
            superseded_by_id=record.superseded_by_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            status=record.status,
            version=record.version,
        )

    @staticmethod
    def _trace_schema(record: MemoryRecallTraceORM) -> MemoryRecallTrace:
        return MemoryRecallTrace.model_validate(record, from_attributes=True)

    @staticmethod
    def _trace_item_schema(record: MemoryRecallTraceItemORM) -> MemoryRecallTraceItem:
        return MemoryRecallTraceItem.model_validate(record, from_attributes=True)
