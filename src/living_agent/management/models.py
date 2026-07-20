"""Database models for staged and deployed managed files."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from living_agent.storage.database import Base


class ArtifactVersionORM(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint("artifact_kind", "artifact_path", "version", name="uq_artifact_version"),
        Index("ix_artifact_versions_kind_path", "artifact_kind", "artifact_path"),
    )

    row_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    artifact_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(512), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ArtifactStageORM(Base):
    __tablename__ = "artifact_stages"
    __table_args__ = (Index("ix_artifact_stages_kind_path", "artifact_kind", "artifact_path"),)

    stage_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    artifact_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(512), nullable=False)
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    validation: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    test_results: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    tested: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
