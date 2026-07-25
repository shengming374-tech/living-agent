"""Configured, brokered memory vector indexing and semantic scoring."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from collections.abc import Iterable

from living_agent.audit.service import AuditService
from living_agent.memory.embedding_repository import (
    MemoryEmbeddingRepository,
    StoredMemoryEmbedding,
)
from living_agent.memory.repository import MemoryNotFoundError, MemoryRepository
from living_agent.models.memory import (
    MemoryEmbeddingStatus,
    MemoryFactuality,
    MemoryLayer,
    MemoryNode,
    MemoryReindexResult,
    MemoryStatus,
)
from living_agent.providers.embeddings import (
    EmbeddingLimitError,
    EmbeddingPermissionError,
    EmbeddingProviderError,
    EmbeddingService,
    EmbeddingStatus,
)
from living_agent.storage.events import EventRepository

_REALITY_FACTUALITIES = {
    MemoryFactuality.VERIFIED,
    MemoryFactuality.REPORTED,
    MemoryFactuality.INFERRED,
}
_INDEX_ERRORS = (EmbeddingLimitError, EmbeddingPermissionError, EmbeddingProviderError)


class MemoryEmbeddingIndex:
    def __init__(
        self,
        *,
        repository: MemoryEmbeddingRepository,
        memories: MemoryRepository,
        embeddings: EmbeddingService,
        events: EventRepository,
        audit: AuditService,
        enabled: bool,
        allow_remote: bool,
        backfill_limit: int,
        min_similarity: float,
    ) -> None:
        self._repository = repository
        self._memories = memories
        self._embeddings = embeddings
        self._events = events
        self._audit = audit
        self._enabled = enabled
        self._allow_remote = allow_remote
        self._backfill_limit = backfill_limit
        self._min_similarity = min_similarity
        self._write_lock = asyncio.Lock()

    @property
    def active(self) -> bool:
        status = self._embeddings.status()
        return self._enabled and (not status.remote or self._allow_remote)

    async def initialize(self) -> MemoryReindexResult:
        return await self.reindex(actor_id="living-agent-startup")

    async def status(self) -> MemoryEmbeddingStatus:
        provider = self._embeddings.status()
        memories = await self._eligible_memories()
        stored = {item.memory_id: item for item in await self._repository.all()}
        current = sum(
            1
            for memory in memories
            if self._current(stored.get(memory.id), memory, provider=provider)
        )
        if not self._enabled:
            reason = "disabled"
        elif provider.remote and not self._allow_remote:
            reason = "remote_provider_not_allowed"
        else:
            reason = "active"
        return MemoryEmbeddingStatus(
            enabled=self._enabled,
            active=self.active,
            reason_code=reason,
            provider=provider.provider,
            model=provider.model,
            remote=provider.remote,
            dimensions=provider.dimensions,
            indexed_count=current,
            eligible_count=len(memories),
            stale_count=len(memories) - current,
        )

    async def reindex(self, *, actor_id: str) -> MemoryReindexResult:
        async with self._write_lock:
            return await self._reindex(actor_id=actor_id)

    async def _reindex(self, *, actor_id: str) -> MemoryReindexResult:
        memories = await self._eligible_memories()
        removed = await self._remove_ineligible_embeddings()
        if not self.active:
            result = MemoryReindexResult(
                indexed_count=0,
                skipped_count=len(memories),
                removed_count=removed,
                failed_count=0,
            )
            await self._audit_reindex(result, actor_id=actor_id)
            return result

        provider = self._embeddings.status()
        to_index: list[MemoryNode] = []
        skipped = 0
        for memory in memories:
            stored = await self._repository.get(memory.id)
            if self._current(stored, memory, provider=provider):
                if stored is not None and stored.memory_version != memory.version:
                    await self._repository.update_version(
                        memory.id,
                        memory_version=memory.version,
                    )
                skipped += 1
            else:
                to_index.append(memory)

        indexed = 0
        failed = 0
        for batch in self._batches(to_index):
            try:
                taint_labels = await self._taint_labels(batch)
                embedding_result = await self._embeddings.generate_automatic(
                    [self._text(memory) for memory in batch],
                    purpose="memory_index",
                    source_event_ids=sorted(
                        {event_id for memory in batch for event_id in memory.source_event_ids}
                    ),
                    taint_labels=taint_labels,
                )
            except _INDEX_ERRORS as exc:
                failed += len(batch)
                await self._audit_failure(
                    action="memory.embedding_index_failed",
                    error_code=self._error_code(exc),
                    memory_ids=[memory.id for memory in batch],
                )
                continue
            for memory, item in zip(batch, embedding_result.data, strict=True):
                await self._repository.upsert(
                    memory_id=memory.id,
                    memory_version=memory.version,
                    provider=provider.provider,
                    model=provider.model,
                    dimensions=embedding_result.dimensions,
                    vector=item.embedding,
                    content_checksum=self._checksum(memory),
                )
                indexed += 1

        reindex_result = MemoryReindexResult(
            indexed_count=indexed,
            skipped_count=skipped,
            removed_count=removed,
            failed_count=failed,
        )
        await self._audit_reindex(reindex_result, actor_id=actor_id)
        return reindex_result

    async def synchronize(self, memory: MemoryNode) -> bool:
        async with self._write_lock:
            return await self._synchronize(memory)

    async def _synchronize(self, memory: MemoryNode) -> bool:
        if not self._eligible(memory):
            await self._repository.delete(memory.id)
            return False
        if not self.active:
            return False
        provider = self._embeddings.status()
        stored = await self._repository.get(memory.id)
        if self._current(stored, memory, provider=provider):
            if stored is not None and stored.memory_version != memory.version:
                await self._repository.update_version(memory.id, memory_version=memory.version)
            return False
        try:
            taint_labels = await self._taint_labels([memory])
            result = await self._embeddings.generate_automatic(
                [self._text(memory)],
                purpose="memory_index",
                source_event_ids=memory.source_event_ids,
                taint_labels=taint_labels,
            )
        except _INDEX_ERRORS as exc:
            await self._audit_failure(
                action="memory.embedding_index_failed",
                error_code=self._error_code(exc),
                memory_ids=[memory.id],
            )
            return False
        await self._repository.upsert(
            memory_id=memory.id,
            memory_version=memory.version,
            provider=provider.provider,
            model=provider.model,
            dimensions=result.dimensions,
            vector=result.data[0].embedding,
            content_checksum=self._checksum(memory),
        )
        await self._audit.append(
            action="memory.embedding_indexed",
            actor_id="living-agent",
            outcome="success",
            details={
                "memory_id": memory.id,
                "memory_version": memory.version,
                "provider": provider.provider,
                "model": provider.model,
                "dimensions": result.dimensions,
            },
        )
        return True

    async def remove(self, memory_id: str) -> bool:
        async with self._write_lock:
            return await self._repository.delete(memory_id)

    async def semantic_scores(
        self,
        query: str,
        memories: list[MemoryNode],
        *,
        source_event_ids: list[str],
        taint_labels: set[str],
    ) -> dict[str, float]:
        if not self.active or not query.strip() or not memories:
            return {}
        try:
            result = await self._embeddings.generate_automatic(
                [self._truncate(query)],
                purpose="memory_query",
                source_event_ids=source_event_ids,
                taint_labels=taint_labels,
            )
        except _INDEX_ERRORS as exc:
            await self._audit_failure(
                action="memory.embedding_query_failed",
                error_code=self._error_code(exc),
                memory_ids=[],
            )
            return {}
        provider = self._embeddings.status()
        stored = await self._repository.for_memories(
            [memory.id for memory in memories],
            provider=provider.provider,
            model=provider.model,
            dimensions=result.dimensions,
        )
        by_id = {memory.id: memory for memory in memories}
        query_vector = result.data[0].embedding
        scores: dict[str, float] = {}
        for memory_id, embedding in stored.items():
            memory = by_id[memory_id]
            if embedding.memory_version != memory.version:
                continue
            score = self._cosine(query_vector, embedding.vector)
            if score >= self._min_similarity:
                scores[memory_id] = score
        return scores

    async def _eligible_memories(self) -> list[MemoryNode]:
        memories = await self._memories.search(
            actor_id="living-agent",
            conversation_id=None,
            owner=True,
            query="",
            include_deleted=False,
            limit=self._backfill_limit,
        )
        return [memory for memory in memories if self._eligible(memory)]

    async def _remove_ineligible_embeddings(self) -> int:
        removed = 0
        for embedding in await self._repository.all():
            try:
                memory = await self._memories.get(embedding.memory_id)
            except MemoryNotFoundError:
                memory = None
            if memory is None or not self._eligible(memory):
                removed += int(await self._repository.delete(embedding.memory_id))
        return removed

    async def _taint_labels(self, memories: list[MemoryNode]) -> set[str]:
        source_ids = sorted(
            {event_id for memory in memories for event_id in memory.source_event_ids}
        )
        events = await self._events.get_many(source_ids)
        return {label for event in events for label in event.taint_labels}

    def _batches(self, memories: list[MemoryNode]) -> Iterable[list[MemoryNode]]:
        status = self._embeddings.status()
        batch: list[MemoryNode] = []
        chars = 0
        for memory in memories:
            text_chars = len(self._text(memory))
            if batch and (
                len(batch) >= status.max_batch_size
                or chars + text_chars > status.max_total_chars
            ):
                yield batch
                batch = []
                chars = 0
            batch.append(memory)
            chars += text_chars
        if batch:
            yield batch

    def _text(self, memory: MemoryNode) -> str:
        content = (
            memory.content
            if isinstance(memory.content, str)
            else json.dumps(memory.content, ensure_ascii=False, sort_keys=True)
        )
        return self._truncate(f"{memory.subject}\n{content}")

    def _truncate(self, text: str) -> str:
        return text[: self._embeddings.status().max_input_chars]

    @staticmethod
    def _eligible(memory: MemoryNode) -> bool:
        return (
            memory.status is MemoryStatus.ACTIVE
            and memory.factuality in _REALITY_FACTUALITIES
            and memory.memory_layer is not MemoryLayer.FACT
        )

    @classmethod
    def _checksum(cls, memory: MemoryNode) -> str:
        return hashlib.sha256(cls._checksum_text(memory).encode("utf-8")).hexdigest()

    @staticmethod
    def _checksum_text(memory: MemoryNode) -> str:
        content = (
            memory.content
            if isinstance(memory.content, str)
            else json.dumps(memory.content, ensure_ascii=False, sort_keys=True)
        )
        return f"{memory.subject}\n{content}"

    @classmethod
    def _current(
        cls,
        stored: StoredMemoryEmbedding | None,
        memory: MemoryNode,
        *,
        provider: EmbeddingStatus,
    ) -> bool:
        if stored is None:
            return False
        return (
            stored.provider == provider.provider
            and stored.model == provider.model
            and (provider.dimensions is None or stored.dimensions == provider.dimensions)
            and stored.content_checksum == cls._checksum(memory)
        )

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            return -1.0
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return -1.0
        return sum(a * b for a, b in zip(left, right, strict=True)) / (
            left_norm * right_norm
        )

    async def _audit_reindex(
        self,
        result: MemoryReindexResult,
        *,
        actor_id: str,
    ) -> None:
        await self._audit.append(
            action="memory.embedding_reindexed",
            actor_id=actor_id,
            outcome="success" if result.failed_count == 0 else "partial",
            details=result.model_dump(mode="json"),
        )

    async def _audit_failure(
        self,
        *,
        action: str,
        error_code: str,
        memory_ids: list[str],
    ) -> None:
        await self._audit.append(
            action=action,
            actor_id="living-agent",
            outcome="failure",
            details={"error_code": error_code, "memory_ids": memory_ids[:32]},
        )

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, EmbeddingProviderError):
            return exc.code
        return type(exc).__name__
