"""Source-aware long-term memory contracts."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def validate_memory_scope(value: str) -> str:
    normalized = value.strip()
    if normalized == "global":
        return normalized
    if re.fullmatch(r"(?:private|conversation):[^:\s]+", normalized) is None:
        raise ValueError("scope must be global, private:<id>, or conversation:<id>")
    return normalized


class MemoryType(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    RELATIONSHIP = "relationship"
    SELF = "self"
    CORE = "core"


class MemoryFactuality(StrEnum):
    VERIFIED = "verified"
    REPORTED = "reported"
    INFERRED = "inferred"
    IMAGINED = "imagined"
    DREAM = "dream"
    FICTIONAL = "fictional"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"


class CandidateStatus(StrEnum):
    PENDING = "pending"
    COMMITTED = "committed"
    REJECTED = "rejected"


class MemoryCandidateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(default_factory=lambda: str(uuid4()))
    type: MemoryType
    content: str | dict[str, Any]
    subject: str
    source_event_ids: list[str] = Field(min_length=1)
    factuality: MemoryFactuality = MemoryFactuality.REPORTED
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    scope: str

    @field_validator("subject", "scope")
    @classmethod
    def require_nonempty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("memory subject and scope cannot be empty")
        return normalized

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        return validate_memory_scope(value)

    @field_validator("source_event_ids")
    @classmethod
    def unique_sources(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("source event IDs must be unique")
        return value


class MemoryCandidate(MemoryCandidateCreate):
    proposer_id: str
    source_trust: str
    status: CandidateStatus
    decision_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class MemoryNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: MemoryType
    content: str | dict[str, Any]
    subject: str
    source_event_ids: list[str]
    source_trust: str
    factuality: MemoryFactuality
    confidence: float = Field(ge=0.0, le=1.0)
    importance: float = Field(ge=0.0, le=1.0)
    scope: str
    created_at: datetime
    updated_at: datetime
    status: MemoryStatus
    version: int = Field(ge=1)


class MemoryUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    content: str | dict[str, Any] | None = None
    subject: str | None = None
    factuality: MemoryFactuality | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    importance: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_change(self) -> MemoryUpdate:
        if self.model_fields_set <= {"expected_version"}:
            raise ValueError("memory update must change at least one field")
        return self

    @field_validator("subject")
    @classmethod
    def validate_optional_subject(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("memory subject cannot be empty")
        return value.strip() if value is not None else None


class MemoryVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: str
    version: int
    snapshot: dict[str, Any]
    change_type: str
    actor_id: str
    created_at: datetime


class MemoryUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usage_id: str
    memory_id: str
    response_id: str
    conversation_id: str
    created_at: datetime


class MemoryEmbeddingStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    active: bool
    reason_code: str
    provider: str
    model: str
    remote: bool
    dimensions: int | None
    indexed_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    stale_count: int = Field(ge=0)


class MemoryReindexResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indexed_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    removed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)


class MemoryFirewallDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason_code: str
    effective_factuality: MemoryFactuality | None = None


class MemoryCommitResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: MemoryCandidate
    decision: MemoryFirewallDecision
    memory: MemoryNode | None = None


class MemoryMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_ids: list[str] = Field(min_length=2)
    type: MemoryType
    content: str | dict[str, Any]
    subject: str
    factuality: MemoryFactuality
    confidence: float = Field(ge=0.0, le=1.0)
    importance: float = Field(ge=0.0, le=1.0)
    scope: str

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        return validate_memory_scope(value)


class MemorySplitPart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: MemoryType
    content: str | dict[str, Any]
    subject: str
    factuality: MemoryFactuality
    confidence: float = Field(ge=0.0, le=1.0)
    importance: float = Field(ge=0.0, le=1.0)
    scope: str

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, value: str) -> str:
        return validate_memory_scope(value)


class MemorySplitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parts: list[MemorySplitPart] = Field(min_length=2)


def utc_now() -> datetime:
    return datetime.now(UTC)
