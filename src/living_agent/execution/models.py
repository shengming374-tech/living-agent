"""Database-only Phase 6 task and report models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from living_agent.storage.database import Base


class TaskRunORM(Base):
    __tablename__ = "task_runs"
    __table_args__ = (
        Index("ix_task_runs_status_updated", "status", "updated_at"),
        Index("ix_task_runs_conversation_updated", "conversation_id", "updated_at"),
    )

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requester_id: Mapped[str] = mapped_column(String(255), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    task_contract: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    execution_plan: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    step_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    taint_labels: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    pending_step_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    activity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class TaskReportORM(Base):
    __tablename__ = "task_reports"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_task_reports_task_id"),
        Index("ix_task_reports_created_at", "created_at"),
    )

    report_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    source_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
