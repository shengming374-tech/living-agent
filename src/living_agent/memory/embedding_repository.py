"""Persistence for current memory embedding vectors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from living_agent.memory.models import MemoryEmbeddingORM


@dataclass(frozen=True, slots=True)
class StoredMemoryEmbedding:
    memory_id: str
    memory_version: int
    provider: str
    model: str
    dimensions: int
    vector: list[float]
    content_checksum: str


class MemoryEmbeddingRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, memory_id: str) -> StoredMemoryEmbedding | None:
        async with self._sessions() as session:
            record = await session.get(MemoryEmbeddingORM, memory_id)
        return self._schema(record) if record is not None else None

    async def upsert(
        self,
        *,
        memory_id: str,
        memory_version: int,
        provider: str,
        model: str,
        dimensions: int,
        vector: list[float],
        content_checksum: str,
    ) -> StoredMemoryEmbedding:
        now = datetime.now(UTC)
        async with self._sessions() as session, session.begin():
            record = await session.get(MemoryEmbeddingORM, memory_id)
            if record is None:
                record = MemoryEmbeddingORM(
                    memory_id=memory_id,
                    memory_version=memory_version,
                    provider=provider,
                    model=model,
                    dimensions=dimensions,
                    vector=vector,
                    content_checksum=content_checksum,
                    created_at=now,
                    updated_at=now,
                )
                session.add(record)
            else:
                record.memory_version = memory_version
                record.provider = provider
                record.model = model
                record.dimensions = dimensions
                record.vector = vector
                record.content_checksum = content_checksum
                record.updated_at = now
        return self._schema(record)

    async def update_version(self, memory_id: str, *, memory_version: int) -> None:
        async with self._sessions() as session, session.begin():
            record = await session.get(MemoryEmbeddingORM, memory_id)
            if record is not None:
                record.memory_version = memory_version
                record.updated_at = datetime.now(UTC)

    async def delete(self, memory_id: str) -> bool:
        async with self._sessions() as session, session.begin():
            record = await session.get(MemoryEmbeddingORM, memory_id)
            if record is None:
                return False
            await session.delete(record)
        return True

    async def for_memories(
        self,
        memory_ids: list[str],
        *,
        provider: str,
        model: str,
        dimensions: int,
    ) -> dict[str, StoredMemoryEmbedding]:
        if not memory_ids:
            return {}
        statement = select(MemoryEmbeddingORM).where(
            MemoryEmbeddingORM.memory_id.in_(memory_ids),
            MemoryEmbeddingORM.provider == provider,
            MemoryEmbeddingORM.model == model,
            MemoryEmbeddingORM.dimensions == dimensions,
        )
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return {record.memory_id: self._schema(record) for record in records}

    async def all(self) -> list[StoredMemoryEmbedding]:
        async with self._sessions() as session:
            records = list((await session.scalars(select(MemoryEmbeddingORM))).all())
        return [self._schema(record) for record in records]

    @staticmethod
    def _schema(record: MemoryEmbeddingORM) -> StoredMemoryEmbedding:
        return StoredMemoryEmbedding(
            memory_id=record.memory_id,
            memory_version=record.memory_version,
            provider=record.provider,
            model=record.model,
            dimensions=record.dimensions,
            vector=record.vector,
            content_checksum=record.content_checksum,
        )
