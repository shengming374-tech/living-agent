"""Durable NapCat ingress idempotency state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from living_agent.storage.database import Base


class NapCatIngressORM(Base):
    __tablename__ = "napcat_ingress_keys"
    __table_args__ = (Index("ix_napcat_ingress_updated", "updated_at"),)

    idempotency_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    self_id: Mapped[str] = mapped_column(String(32), nullable=False)
    message_id: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NapCatIngressDisposition(StrEnum):
    NEW = "new"
    REPLAY = "replay"
    CONFLICT = "conflict"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class NapCatIngressClaim:
    disposition: NapCatIngressDisposition


def _now() -> datetime:
    return datetime.now(UTC)


def _key_hash(key: tuple[str, str]) -> str:
    return hashlib.sha256("\x1f".join(key).encode("utf-8")).hexdigest()


class NapCatIngressRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def claim(
        self,
        key: tuple[str, str],
        *,
        fingerprint: str,
    ) -> NapCatIngressClaim:
        now = _now()
        record = NapCatIngressORM(
            idempotency_key=_key_hash(key),
            self_id=key[0],
            message_id=key[1],
            fingerprint=fingerprint,
            state="processing",
            failure_code=None,
            created_at=now,
            updated_at=now,
        )
        async with self._sessions() as database_session:
            database_session.add(record)
            try:
                await database_session.commit()
                return NapCatIngressClaim(NapCatIngressDisposition.NEW)
            except IntegrityError:
                await database_session.rollback()
        return await self._existing(record.idempotency_key, fingerprint=fingerprint)

    async def complete(self, key: tuple[str, str], *, fingerprint: str) -> None:
        await self._finish(
            key,
            fingerprint=fingerprint,
            state="completed",
            failure_code=None,
        )

    async def fail(
        self,
        key: tuple[str, str],
        *,
        fingerprint: str,
        failure_code: str,
    ) -> None:
        await self._finish(
            key,
            fingerprint=fingerprint,
            state="failed",
            failure_code=failure_code[:100],
        )

    async def _finish(
        self,
        key: tuple[str, str],
        *,
        fingerprint: str,
        state: str,
        failure_code: str | None,
    ) -> None:
        async with self._sessions() as database_session, database_session.begin():
            record = await self._locked(database_session, _key_hash(key))
            if (
                record is None
                or record.fingerprint != fingerprint
                or record.state != "processing"
            ):
                return
            record.state = state
            record.failure_code = failure_code
            record.updated_at = _now()

    async def _existing(
        self,
        idempotency_key: str,
        *,
        fingerprint: str,
    ) -> NapCatIngressClaim:
        async with self._sessions() as database_session:
            record = await database_session.get(NapCatIngressORM, idempotency_key)
        if record is None:
            raise RuntimeError("NapCat ingress key conflicted but could not be loaded")
        if record.fingerprint != fingerprint:
            return NapCatIngressClaim(NapCatIngressDisposition.CONFLICT)
        if record.state == "completed":
            return NapCatIngressClaim(NapCatIngressDisposition.REPLAY)
        return NapCatIngressClaim(NapCatIngressDisposition.INCOMPLETE)

    @staticmethod
    async def _locked(
        database_session: AsyncSession,
        idempotency_key: str,
    ) -> NapCatIngressORM | None:
        statement = (
            select(NapCatIngressORM)
            .where(NapCatIngressORM.idempotency_key == idempotency_key)
            .with_for_update()
        )
        record: NapCatIngressORM | None = await database_session.scalar(statement)
        return record
