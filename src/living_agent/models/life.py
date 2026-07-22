"""Phase 8 contracts for projects, daily life, sleep, dreams, and change proposals."""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class PrivateProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4000)
    goals: list[str] = Field(default_factory=list, max_length=30)


class PrivateProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, min_length=1, max_length=4000)
    goals: list[str] | None = Field(default=None, max_length=30)
    status: ProjectStatus | None = None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.model_fields_set <= {"expected_version"}:
            raise ValueError("project update must change at least one field")
        return self


class PrivateProject(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    project_id: str
    title: str
    summary: str
    goals: list[str]
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class PlanItemKind(StrEnum):
    ROUTINE = "routine"
    PROJECT = "project"
    SOCIAL = "social"
    CREATIVE = "creative"
    REST = "rest"


class PlanItemStatus(StrEnum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class DailyPlanStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"


class DailyPlanItemInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(default_factory=new_id)
    title: str = Field(min_length=1, max_length=300)
    kind: PlanItemKind
    project_id: str | None = None
    scheduled_for: datetime | None = None
    expected_minutes: int = Field(default=30, ge=1, le=1440)
    status: PlanItemStatus = PlanItemStatus.PLANNED

    @field_validator("scheduled_for")
    @classmethod
    def require_aware_schedule(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("scheduled_for must include a timezone")
        return value


class DailyPlanUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = Field(default=None, ge=1)
    intention: str = Field(min_length=1, max_length=1000)
    items: list[DailyPlanItemInput] = Field(min_length=1, max_length=50)

    @field_validator("items")
    @classmethod
    def unique_item_ids(cls, value: list[DailyPlanItemInput]) -> list[DailyPlanItemInput]:
        ids = [item.item_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("daily plan item ids must be unique")
        return value


class DailyPlan(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    plan_id: str
    plan_date: date
    intention: str
    items: list[DailyPlanItemInput]
    status: DailyPlanStatus
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class PlanItemStatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    status: PlanItemStatus


class LifeActivityStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LifeActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(default="", max_length=4000)
    project_id: str | None = None
    plan_id: str | None = None
    plan_item_id: str | None = None


class LifeActivityFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        LifeActivityStatus.COMPLETED,
        LifeActivityStatus.FAILED,
        LifeActivityStatus.CANCELLED,
    ]
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    summary: str | None = Field(default=None, max_length=4000)


class LifeActivityLog(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    activity_id: str
    kind: str
    title: str
    summary: str
    project_id: str | None
    plan_id: str | None
    plan_item_id: str | None
    status: LifeActivityStatus
    evidence_ids: list[str]
    started_at: datetime
    finished_at: datetime | None


class DiaryStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class DiaryUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = Field(default=None, ge=1)
    content: str = Field(min_length=1, max_length=20_000)
    mood_summary: str = Field(default="", max_length=1000)
    status: DiaryStatus = DiaryStatus.DRAFT
    source_activity_ids: list[str] = Field(default_factory=list, max_length=200)
    source_memory_ids: list[str] = Field(default_factory=list, max_length=200)
    dream_record_ids: list[str] = Field(default_factory=list, max_length=50)


class DiaryEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    diary_id: str
    entry_date: date
    content: str
    mood_summary: str
    status: DiaryStatus
    generated_by: str
    source_activity_ids: list[str]
    source_memory_ids: list[str]
    dream_record_ids: list[str]
    created_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class SleepCycleStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DreamRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    dream_id: str
    cycle_id: str
    dream_date: date
    content: str
    seed_activity_ids: list[str]
    seed_memory_ids: list[str]
    factuality: Literal["dream"] = "dream"
    reality_eligible: Literal[False] = False
    created_at: datetime


class SleepCycle(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    cycle_id: str
    cycle_date: date
    trigger: str
    status: SleepCycleStatus
    diary_id: str | None
    dream_id: str | None
    reality_memory_ids: list[str]
    candidate_review_ids: list[str]
    duplicate_memory_clusters: list[list[str]]
    thought_record_ids: list[str]
    activity_ids: list[str]
    automatic_memory_writes: Literal[0] = 0
    error_code: str | None
    started_at: datetime
    finished_at: datetime | None


class SleepCycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_date: date | None = None


class SelfChangeTargetKind(StrEnum):
    PERSONA = "persona"
    PROMPT = "prompt"


class SelfChangeProposalStatus(StrEnum):
    READY = "ready"
    TEST_FAILED = "test_failed"
    DEPLOYED = "deployed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class SelfChangeProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_kind: SelfChangeTargetKind
    target_path: str = Field(min_length=1, max_length=200)
    expected_version: int = Field(ge=1)
    proposed_content: str = Field(min_length=1, max_length=200_000)
    rationale: str = Field(min_length=1, max_length=4000)
    source_diary_ids: list[str] = Field(default_factory=list, max_length=50)
    source_dream_ids: list[str] = Field(default_factory=list, max_length=50)


class SelfChangeProposal(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    proposal_id: str
    proposer_id: Literal["living-agent"]
    target_kind: SelfChangeTargetKind
    target_path: str
    base_version: int
    proposed_content: str
    rationale: str
    source_diary_ids: list[str]
    source_dream_ids: list[str]
    stage_id: str
    diff: str
    test_results: dict[str, Any]
    status: SelfChangeProposalStatus
    approved_by: str | None
    deployed_version: int | None
    created_at: datetime
    updated_at: datetime
