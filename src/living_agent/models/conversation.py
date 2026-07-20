"""Conversation participation and API result schemas."""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

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


class SpeechUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    function: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=4000)
    delay_min_ms: int = Field(ge=0, le=10000)
    delay_max_ms: int = Field(ge=0, le=10000)
    cancellable: bool


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
    message: str | None
    messages: list[str] = Field(default_factory=list, max_length=3)
    utterance: UtteranceSession | None = None
