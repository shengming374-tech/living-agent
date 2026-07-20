"""Registered stable-user profile contracts without authority state."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from living_agent.models.events import SourceType


class UserProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=200)
    source_type: SourceType
    first_seen_at: datetime
    last_seen_at: datetime
    message_count: int = Field(ge=1)
    last_conversation_id: str | None = Field(default=None, max_length=255)
