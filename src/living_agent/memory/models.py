"""Database-only models for candidate, committed, version, and usage memory data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from living_agent.storage.database import Base


class MemoryCandidateORM(Base):
    __tablename__ = "memory_candidates"

    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    memory_type: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_trust: Mapped[str] = mapped_column(String(40), nullable=False)
    factuality: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    importance: Mapped[float] = mapped_column(Float, nullable=False)
    scope: Mapped[str] = mapped_column(String(512), nullable=False)
    memory_layer: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    memory_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    superseded_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    decision_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryNodeORM(Base):
    __tablename__ = "memory_nodes"
    __table_args__ = (
        Index("ix_memory_nodes_scope_status", "scope", "status"),
        Index("ix_memory_nodes_subject_type", "subject", "memory_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_type: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    searchable_text: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_trust: Mapped[str] = mapped_column(String(40), nullable=False)
    factuality: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    importance: Mapped[float] = mapped_column(Float, nullable=False)
    scope: Mapped[str] = mapped_column(String(512), nullable=False)
    memory_layer: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    memory_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    superseded_by_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class MemoryVersionORM(Base):
    __tablename__ = "memory_versions"
    __table_args__ = (
        UniqueConstraint("memory_id", "version", name="uq_memory_version"),
        Index("ix_memory_versions_memory_id", "memory_id"),
    )

    row_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryUsageORM(Base):
    __tablename__ = "memory_usages"
    __table_args__ = (Index("ix_memory_usages_memory_id", "memory_id"),)

    usage_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_id: Mapped[str] = mapped_column(String(36), nullable=False)
    response_id: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryRecallTraceORM(Base):
    __tablename__ = "memory_recall_traces"
    __table_args__ = (
        Index(
            "ix_memory_recall_traces_conversation_created",
            "conversation_id",
            "created_at",
        ),
        Index("ix_memory_recall_traces_event_id", "event_id"),
        Index("ix_memory_recall_traces_response_id", "response_id"),
    )

    trace_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    response_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    conversation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    route: Mapped[str] = mapped_column(String(40), nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    context_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    support_mode: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryRecallTraceItemORM(Base):
    __tablename__ = "memory_recall_trace_items"
    __table_args__ = (
        UniqueConstraint(
            "trace_id",
            "memory_id",
            name="uq_memory_recall_trace_item",
        ),
        Index(
            "ix_memory_recall_trace_items_trace_selected",
            "trace_id",
            "selected",
        ),
        Index("ix_memory_recall_trace_items_memory_id", "memory_id"),
    )

    row_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    memory_id: Mapped[str] = mapped_column(String(36), nullable=False)
    memory_layer: Mapped[str] = mapped_column(String(40), nullable=False)
    selection_reason: Mapped[str] = mapped_column(String(120), nullable=False)
    lexical_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    semantic_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    final_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    injected: Mapped[bool] = mapped_column(Boolean, nullable=False)
    response_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    source_overlap: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MemoryEmbeddingORM(Base):
    __tablename__ = "memory_embeddings"
    __table_args__ = (
        Index("ix_memory_embeddings_provider_model", "provider", "model"),
    )

    memory_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    memory_version: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(255), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    content_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
