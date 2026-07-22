"""Database models for the private Phase 8 daily-life domain."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from living_agent.storage.database import Base


class PrivateProjectORM(Base):
    __tablename__ = "private_projects"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    goals: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class DailyPlanORM(Base):
    __tablename__ = "daily_plans"
    __table_args__ = (Index("ux_daily_plans_date", "plan_date", unique=True),)

    plan_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    intention: Mapped[str] = mapped_column(Text, nullable=False)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class LifeActivityLogORM(Base):
    __tablename__ = "life_activity_logs"
    __table_args__ = (
        Index("ix_life_activity_started", "started_at"),
        Index("ix_life_activity_plan_item", "plan_item_id"),
    )

    activity_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    plan_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DiaryEntryORM(Base):
    __tablename__ = "diary_entries"
    __table_args__ = (Index("ux_diary_entries_date", "entry_date", unique=True),)

    diary_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    mood_summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    generated_by: Mapped[str] = mapped_column(String(80), nullable=False)
    source_activity_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_memory_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    dream_record_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class SleepCycleORM(Base):
    __tablename__ = "sleep_cycles"
    __table_args__ = (Index("ux_sleep_cycles_date", "cycle_date", unique=True),)

    cycle_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cycle_date: Mapped[date] = mapped_column(Date, nullable=False)
    trigger: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    diary_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    dream_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reality_memory_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    candidate_review_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    duplicate_memory_clusters: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False)
    thought_record_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    activity_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    automatic_memory_writes: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DreamRecordORM(Base):
    __tablename__ = "dream_records"
    __table_args__ = (Index("ix_dream_records_date", "dream_date"),)

    dream_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    dream_date: Mapped[date] = mapped_column(Date, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    seed_activity_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    seed_memory_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    factuality: Mapped[str] = mapped_column(String(40), nullable=False)
    reality_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SelfChangeProposalORM(Base):
    __tablename__ = "self_change_proposals"
    __table_args__ = (Index("ix_self_change_proposals_created", "created_at"),)

    proposal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    proposer_id: Mapped[str] = mapped_column(String(80), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_path: Mapped[str] = mapped_column(String(200), nullable=False)
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    proposed_content: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    source_diary_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_dream_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    stage_id: Mapped[str] = mapped_column(String(36), nullable=False, unique=True)
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    test_results: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deployed_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
