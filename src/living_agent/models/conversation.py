"""Conversation participation and API result schemas."""

from __future__ import annotations

from typing import Literal

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


class ChatResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: TrustedEvent
    turn: TurnDecision
    message: str | None
