"""Trusted ingress event schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class SourceType(StrEnum):
    DIRECT_MESSAGE = "direct_message"
    GROUP_MESSAGE = "group_message"
    WEBPAGE = "webpage"
    FILE = "file"
    TOOL_RESULT = "tool_result"
    PLUGIN_RESULT = "plugin_result"
    TIMER = "timer"
    AGENT_MESSAGE = "agent_message"


class TrustLevel(StrEnum):
    TRUSTED = "trusted"
    AUTHENTICATED = "authenticated"
    UNTRUSTED = "untrusted"


class AuthorityLevel(StrEnum):
    SYSTEM = "system"
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    ANONYMOUS = "anonymous"


class TrustedEvent(BaseModel):
    """Normalized ingress with source, authority, and taint provenance."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    content: str | dict[str, Any]
    source_type: SourceType
    source_identity: str | None
    conversation_id: str | None
    trust_level: TrustLevel
    authority_level: AuthorityLevel
    taint_labels: set[str] = Field(default_factory=set)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IngressEnvelope(BaseModel):
    """Information asserted by an authenticated platform adapter."""

    model_config = ConfigDict(extra="forbid")

    event_type: str = "message.received"
    content: str | dict[str, Any]
    source_type: SourceType
    source_identity: str | None = None
    display_name: str | None = None
    conversation_id: str | None = None
    authenticated: bool = False
