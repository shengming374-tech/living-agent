"""Database model for durable interruptible utterance Sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from living_agent.storage.database import Base


class UtteranceSessionORM(Base):
    __tablename__ = "utterance_sessions"
    __table_args__ = (
        Index(
            "ix_utterance_sessions_scope_state",
            "platform",
            "conversation_id",
            "state",
        ),
        Index(
            "ix_utterance_sessions_conversation_updated",
            "conversation_id",
            "updated_at",
        ),
    )

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(500), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    intention: Mapped[str] = mapped_column(Text(), nullable=False)
    units: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    recalled_memory_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    started_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    interruption_policy: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    generation: Mapped[int] = mapped_column(Integer(), nullable=False)
    replaced_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    interruption_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
