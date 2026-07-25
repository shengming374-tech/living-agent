"""Conversation participation and API result schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from living_agent.models.events import TrustedEvent


class TurnDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["observe", "react", "engage", "act"]
    urgency: float = Field(ge=0.0, le=1.0)
    expected_units_min: int = Field(ge=0)
    expected_units_max: int = Field(ge=0)
    interruption_tolerance: float = Field(ge=0.0, le=1.0)
    target_event_ids: list[str]
    reason_code: str


class TurnScheduleDecision(BaseModel):
    """Host-owned decision about whether the social planner should run now."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["trigger", "wait", "delay", "suppress"]
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(min_length=1, max_length=12)
    pending_event_ids: list[str] = Field(default_factory=list, max_length=32)
    delay_seconds: float | None = Field(default=None, ge=0.0, le=86400.0)


class ConversationRuntimeState(BaseModel):
    """Durable attention and scheduling state for one conversation."""

    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    pending_event_ids: list[str] = Field(default_factory=list, max_length=32)
    focus_salience: float = Field(ge=0.0, le=1.0)
    is_focused: bool
    forced_wakeup: bool
    consecutive_idle_count: int = Field(ge=0)
    cooldown_until: datetime | None = None
    next_evaluation_at: datetime | None = None
    last_external_at: datetime
    last_agent_at: datetime | None = None
    updated_at: datetime
    version: int = Field(ge=1)


class SessionImpression(BaseModel):
    """A sourced, expiring conversation summary that is not a factual memory."""

    model_config = ConfigDict(extra="forbid")

    impression_id: str = Field(default_factory=lambda: str(uuid4()))
    conversation_id: str
    summary: str = Field(min_length=1, max_length=1200)
    topics: list[str] = Field(default_factory=list, max_length=8)
    unresolved_threads: list[str] = Field(default_factory=list, max_length=6)
    emotional_tone: str = Field(min_length=1, max_length=80)
    participant_cues: list[str] = Field(default_factory=list, max_length=8)
    source_event_ids: list[str] = Field(min_length=1, max_length=64)
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime


class AttentionCue(BaseModel):
    """A one-use association grounded in recent conversation evidence."""

    model_config = ConfigDict(extra="forbid")

    cue_id: str = Field(default_factory=lambda: str(uuid4()))
    conversation_id: str
    cue_text: str = Field(min_length=1, max_length=500)
    topic: str = Field(min_length=1, max_length=200)
    source_event_ids: list[str] = Field(min_length=1, max_length=32)
    salience: float = Field(ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    used: bool = False


class SpeechUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    function: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=4000)
    delay_min_ms: int = Field(ge=0, le=10000)
    delay_max_ms: int = Field(ge=0, le=10000)
    cancellable: bool

    @model_validator(mode="after")
    def validate_delay_range(self) -> SpeechUnit:
        if self.delay_min_ms > self.delay_max_ms:
            raise ValueError("speech unit delay_min_ms cannot exceed delay_max_ms")
        return self


class UtteranceSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    intention: str = Field(min_length=1, max_length=500)
    units: list[SpeechUnit] = Field(min_length=1, max_length=3)
    sent_count: int = Field(default=0, ge=0)
    interruption_policy: str = Field(min_length=1, max_length=100)
    state: Literal["planned", "sending", "completed", "cancelled"] = "planned"


class ChatResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: TrustedEvent
    turn: TurnDecision
    schedule: TurnScheduleDecision | None = None
    message: str | None
    messages: list[str] = Field(default_factory=list, max_length=3)
    utterance: UtteranceSession | None = None
    recalled_memory_ids: list[str] = Field(default_factory=list, max_length=8)
    memory_trace_id: str | None = None
    attention_cue_id: str | None = None
