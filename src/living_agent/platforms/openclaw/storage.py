"""Durable OpenClaw ingress idempotency state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from living_agent.platforms.openclaw.models import OpenClawBridgeResponse
from living_agent.storage.database import Base


class OpenClawIngressORM(Base):
    __tablename__ = "openclaw_ingress_keys"
    __table_args__ = (Index("ix_openclaw_ingress_updated", "updated_at"),)

    idempotency_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(255), nullable=False)
    account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IngressClaimDisposition(StrEnum):
    NEW = "new"
    REPLAY = "replay"
    CONFLICT = "conflict"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class IngressClaim:
    disposition: IngressClaimDisposition
    response: OpenClawBridgeResponse | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _key_hash(key: tuple[str, str, str]) -> str:
    encoded = "\x1f".join(key).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class OpenClawIngressRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def claim(
        self,
        key: tuple[str, str, str],
        *,
        fingerprint: str,
    ) -> IngressClaim:
        idempotency_key = _key_hash(key)
        now = _now()
        record = OpenClawIngressORM(
            idempotency_key=idempotency_key,
            channel_id=key[0],
            account_id=key[1],
            message_id=key[2],
            fingerprint=fingerprint,
            state="processing",
            response=None,
            failure_code=None,
            created_at=now,
            updated_at=now,
        )
        async with self._sessions() as database_session:
            database_session.add(record)
            try:
                await database_session.commit()
                return IngressClaim(IngressClaimDisposition.NEW)
            except IntegrityError:
                await database_session.rollback()
        return await self._existing(idempotency_key, fingerprint=fingerprint)

    async def complete(
        self,
        key: tuple[str, str, str],
        *,
        fingerprint: str,
        response: OpenClawBridgeResponse,
    ) -> None:
        async with self._sessions() as database_session, database_session.begin():
            record = await self._locked(database_session, _key_hash(key))
            if record is None or record.fingerprint != fingerprint:
                raise RuntimeError("OpenClaw ingress claim disappeared before completion")
            if record.state == "completed":
                return
            if record.state != "processing":
                raise RuntimeError("OpenClaw ingress claim is not processing")
            replay = response.model_copy(
                update={
                    "message": None,
                    "messages": [],
                    "unit_delays_ms": [],
                    "utterance_session_id": None,
                    "reason_code": "idempotent_replay",
                }
            )
            record.response = replay.model_dump(mode="json")
            record.state = "completed"
            record.updated_at = _now()

    async def fail(
        self,
        key: tuple[str, str, str],
        *,
        fingerprint: str,
        failure_code: str,
    ) -> None:
        async with self._sessions() as database_session, database_session.begin():
            record = await self._locked(database_session, _key_hash(key))
            if (
                record is None
                or record.fingerprint != fingerprint
                or record.state != "processing"
            ):
                return
            record.state = "failed"
            record.failure_code = failure_code[:100]
            record.updated_at = _now()

    async def _existing(self, idempotency_key: str, *, fingerprint: str) -> IngressClaim:
        async with self._sessions() as database_session:
            record = await database_session.get(OpenClawIngressORM, idempotency_key)
        if record is None:
            raise RuntimeError("OpenClaw ingress key conflicted but could not be loaded")
        if record.fingerprint != fingerprint:
            return IngressClaim(IngressClaimDisposition.CONFLICT)
        if record.state == "completed" and record.response is not None:
            return IngressClaim(
                IngressClaimDisposition.REPLAY,
                OpenClawBridgeResponse.model_validate(record.response),
            )
        return IngressClaim(IngressClaimDisposition.INCOMPLETE)

    @staticmethod
    async def _locked(
        database_session: AsyncSession,
        idempotency_key: str,
    ) -> OpenClawIngressORM | None:
        statement = (
            select(OpenClawIngressORM)
            .where(OpenClawIngressORM.idempotency_key == idempotency_key)
            .with_for_update()
        )
        record: OpenClawIngressORM | None = await database_session.scalar(statement)
        return record
