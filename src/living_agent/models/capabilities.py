"""Capability proposal, grant, and decision contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class DecisionOutcome(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ASK_OWNER = "ASK_OWNER"
    ALLOW_ONCE = "ALLOW_ONCE"
    ALLOW_READ_ONLY = "ALLOW_READ_ONLY"
    ALLOW_IN_SANDBOX = "ALLOW_IN_SANDBOX"
    ALLOW_WITH_REDACTION = "ALLOW_WITH_REDACTION"


class CapabilityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=lambda: str(uuid4()))
    actor_id: str
    capability: str
    operation: str
    resource_scope: str
    arguments: dict[str, Any]
    source_event_ids: list[str]
    taint_labels: set[str] = Field(default_factory=set)
    reason: str
    conversation_id: str | None = None


class CapabilityGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: str = Field(default_factory=lambda: str(uuid4()))
    actor_id: str
    capability: str
    operations: set[str]
    resource_scopes: set[str]
    conversation_id: str | None = None
    one_time: bool = True


class CapabilityDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    outcome: DecisionOutcome
    reason_code: str
    explanation: str
    effective_scope: str | None = None


class CapabilityDefinitionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    operations: list[str]
    argument_schema: str
    sandbox_required: bool
    scope_bound: bool


class CapabilitySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definitions: list[CapabilityDefinitionView]
    active_grants: list[CapabilityGrant]
