"""Database-only models for trusted events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from living_agent.storage.database import Base


class TrustedEventORM(Base):
    __tablename__ = "trusted_events"
    __table_args__ = (
        Index("ix_trusted_events_conversation_created", "conversation_id", "created_at"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    trust_level: Mapped[str] = mapped_column(String(40), nullable=False)
    authority_level: Mapped[str] = mapped_column(String(40), nullable=False)
    taint_labels: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
