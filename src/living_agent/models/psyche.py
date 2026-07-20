"""Persistent psyche, safe thought summary, topic, and activity contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

ThoughtKind = Literal[
    "reaction",
    "concern",
    "association",
    "intention",
    "doubt",
    "suppressed_reply",
    "task_observation",
    "memory_trigger",
]


class ThoughtRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thought_id: str = Field(default_factory=lambda: str(uuid4()))
    kind: ThoughtKind
    summary: str = Field(min_length=1, max_length=1000)
    source_event_ids: list[str]
    intensity: float = Field(ge=0.0, le=1.0)
    speakability: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    resolved: bool = False


class ThoughtRecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ThoughtKind
    summary: str = Field(min_length=1, max_length=1000)
    source_event_ids: list[str] = Field(min_length=1)
    intensity: float = Field(ge=0.0, le=1.0)
    speakability: float = Field(ge=0.0, le=1.0)
    expires_at: datetime | None = None


class TopicStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class UnresolvedTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_id: str
    summary: str
    source_event_ids: list[str]
    status: TopicStatus
    created_at: datetime
    resolved_at: datetime | None = None


class UnresolvedTopicCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=1000)
    source_event_ids: list[str] = Field(min_length=1)


class ActivityStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ActivityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    activity_id: str
    kind: str
    summary: str
    source_event_ids: list[str]
    status: ActivityStatus
    evidence_ids: list[str]
    started_at: datetime
    finished_at: datetime | None = None


class PsycheState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state_id: str
    valence: float = Field(ge=-1.0, le=1.0)
    arousal: float = Field(ge=0.0, le=1.0)
    current_focus: str | None
    focus_salience: float = Field(ge=0.0, le=1.0)
    unresolved_topic_ids: list[str]
    current_activity_id: str | None
    last_decay_at: datetime
    updated_at: datetime
    version: int = Field(ge=1)


class PsycheStateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valence: float | None = Field(default=None, ge=-1.0, le=1.0)
    arousal: float | None = Field(default=None, ge=0.0, le=1.0)
    current_focus: str | None = Field(default=None, max_length=500)
    focus_salience: float | None = Field(default=None, ge=0.0, le=1.0)
