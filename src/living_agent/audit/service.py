"""Append and query audit records with secret redaction."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from living_agent.audit.models import AuditEntry, AuditRecordORM

_SENSITIVE_KEYS = frozenset({"api_key", "password", "secret", "token", "authorization"})
_SENSITIVE_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(api[_ -]?key|password|secret|token)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)\bbearer\s+[a-z0-9._~-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)


def redact_text(value: str) -> str:
    redacted = value
    redacted = _SENSITIVE_TEXT_PATTERNS[0].sub(r"\1: [REDACTED]", redacted)
    redacted = _SENSITIVE_TEXT_PATTERNS[1].sub("Bearer [REDACTED]", redacted)
    return _SENSITIVE_TEXT_PATTERNS[2].sub("[REDACTED]", redacted)


def redact(value: Any) -> Any:
    """Recursively redact values whose keys commonly carry credentials."""

    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in _SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, set):
        return sorted(redact(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


class AuditService:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def append(
        self,
        *,
        action: str,
        outcome: str,
        actor_id: str | None = None,
        conversation_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> AuditEntry:
        record = AuditRecordORM(
            audit_id=str(uuid4()),
            action=action,
            actor_id=actor_id,
            conversation_id=conversation_id,
            outcome=outcome,
            details=redact(details or {}),
            created_at=datetime.now(UTC),
        )
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
            await session.refresh(record)
        return AuditEntry.model_validate(record)

    async def list_entries(self, *, limit: int = 100) -> list[AuditEntry]:
        statement = select(AuditRecordORM).order_by(AuditRecordORM.created_at.desc()).limit(limit)
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [AuditEntry.model_validate(record) for record in records]
