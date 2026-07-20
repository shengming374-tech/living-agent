"""Database-only psyche, thought, topic, and activity models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from living_agent.storage.database import Base


class PsycheStateORM(Base):
    __tablename__ = "psyche_states"

    state_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    valence: Mapped[float] = mapped_column(Float, nullable=False)
    arousal: Mapped[float] = mapped_column(Float, nullable=False)
    current_focus: Mapped[str | None] = mapped_column(String(500), nullable=True)
    focus_salience: Mapped[float] = mapped_column(Float, nullable=False)
    unresolved_topic_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    current_activity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    last_decay_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class ThoughtRecordORM(Base):
    __tablename__ = "thought_records"
    __table_args__ = (Index("ix_thought_records_created_at", "created_at"),)

    thought_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    intensity: Mapped[float] = mapped_column(Float, nullable=False)
    speakability: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False)


class UnresolvedTopicORM(Base):
    __tablename__ = "psyche_topics"

    topic_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActivityRecordORM(Base):
    __tablename__ = "activity_records"
    __table_args__ = (Index("ix_activity_records_started_at", "started_at"),)

    activity_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
