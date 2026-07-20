"""Audit database model and public schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from living_agent.storage.database import Base


class AuditRecordORM(Base):
    __tablename__ = "audit_records"
    __table_args__ = (
        Index("ix_audit_records_created_at", "created_at"),
        Index("ix_audit_records_action_created", "action", "created_at"),
    )

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    audit_id: str
    action: str
    actor_id: str | None
    conversation_id: str | None
    outcome: str
    details: dict[str, Any]
    created_at: datetime
