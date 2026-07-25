"""Database model for durable interruptible utterance Sessions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
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
    memory_trace_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attention_cue_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sent_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    started_count: Mapped[int] = mapped_column(Integer(), nullable=False)
    interruption_policy: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(40), nullable=False)
    generation: Mapped[int] = mapped_column(Integer(), nullable=False)
    replaced_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    interruption_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationRuntimeStateORM(Base):
    __tablename__ = "conversation_runtime_states"
    __table_args__ = (
        Index("ix_conversation_runtime_focus", "is_focused", "focus_salience"),
        Index("ix_conversation_runtime_updated", "updated_at"),
    )

    conversation_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    pending_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    focus_salience: Mapped[float] = mapped_column(Float, nullable=False)
    is_focused: Mapped[bool] = mapped_column(Boolean, nullable=False)
    forced_wakeup: Mapped[bool] = mapped_column(Boolean, nullable=False)
    consecutive_idle_count: Mapped[int] = mapped_column(Integer, nullable=False)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_evaluation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_external_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_agent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class SessionImpressionORM(Base):
    __tablename__ = "session_impressions"
    __table_args__ = (
        Index("ix_session_impressions_conversation_created", "conversation_id", "created_at"),
    )

    impression_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    topics: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    unresolved_threads: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    emotional_tone: Mapped[str] = mapped_column(String(80), nullable=False)
    participant_cues: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AttentionCueORM(Base):
    __tablename__ = "attention_cues"
    __table_args__ = (
        Index("ix_attention_cues_conversation_created", "conversation_id", "created_at"),
    )

    cue_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    cue_text: Mapped[str] = mapped_column(Text, nullable=False)
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    salience: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False)
