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
    if (
        re.fullmatch(
            r"(?:private|conversation):[^:\s]+(?::[^:\s]+)*",
            normalized,
        )
        is None
    ):
        raise ValueError("scope must be global, private:<id>, or conversation:<id>")
    return normalized


class MemoryType(StrEnum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    RELATIONSHIP = "relationship"
    SELF = "self"
    CORE = "core"


class MemoryLayer(StrEnum):
    FACT = "fact"
    NARRATIVE = "narrative"
    LEGACY = "legacy"


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


class MemorySupportMode(StrEnum):
    PENDING = "pending"
    MEMORY_ONLY = "memory_only"
    CORROBORATED = "corroborated"
    INJECTED_UNVERIFIED = "injected_unverified"
    NOT_INJECTED = "not_injected"


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
    memory_layer: MemoryLayer | None = None
    entity_id: str | None = None
    memory_key: str | None = None
    valid_until: datetime | None = None
    superseded_by_id: str | None = None

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
    memory_layer: MemoryLayer | None = None
    entity_id: str | None = None
    memory_key: str | None = None
    valid_until: datetime | None = None
    superseded_by_id: str | None = None
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


class MemoryRecallTraceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    event_id: str
    response_id: str | None = None
    conversation_id: str
    actor_id: str
    route: str
    query_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    context_fingerprint: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    support_mode: MemorySupportMode = MemorySupportMode.PENDING


class MemoryRecallTrace(MemoryRecallTraceCreate):
    created_at: datetime
    updated_at: datetime


class MemoryRecallTraceItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_id: str = Field(default_factory=lambda: str(uuid4()))
    trace_id: str
    memory_id: str
    memory_layer: MemoryLayer
    selection_reason: str
    lexical_score: float | None = None
    semantic_score: float | None = None
    final_score: float | None = None
    selected: bool = False
    injected: bool = False
    response_match: bool | None = None
    source_overlap: bool = False


class MemoryRecallTraceItem(MemoryRecallTraceItemCreate):
    created_at: datetime
    updated_at: datetime


class MemoryRecallTraceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace: MemoryRecallTrace
    items: list[MemoryRecallTraceItem] = Field(default_factory=list)


class MemoryRecallBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memories: list[MemoryNode] = Field(default_factory=list, max_length=8)
    trace_id: str
    route: str


class MemoryProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_id: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=1, max_length=500)
    fact_keys: list[str] = Field(min_length=1, max_length=8)

    @field_validator("subject_id", "prompt")
    @classmethod
    def normalize_probe_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("fact_keys")
    @classmethod
    def normalize_fact_keys(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if not normalized:
            raise ValueError("at least one fact key is required")
        if len(normalized) != len(set(normalized)):
            raise ValueError("fact keys must be unique")
        return normalized


class MemoryProbeVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    selected_memory_ids: list[str] = Field(default_factory=list, max_length=8)


class MemoryProbeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: str
    support_mode: MemorySupportMode
    with_memory: MemoryProbeVariant
    without_memory: MemoryProbeVariant
    trace_id: str


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
