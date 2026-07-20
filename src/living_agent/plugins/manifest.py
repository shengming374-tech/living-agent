"""Strict native plugin manifest schema."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PluginType(StrEnum):
    TOOL = "tool"
    SKILL = "skill"
    PLATFORM_ADAPTER = "platform_adapter"
    BACKGROUND_SERVICE = "background_service"
    PERSONA_PACK = "persona_pack"
    CORE_EXTENSION = "core_extension"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CapabilityDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operations: set[str] = Field(default_factory=set)
    scopes: set[str] = Field(default_factory=set)


class PluginOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    capability: str
    broker_operation: str
    resource_scope: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class PluginDataPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stores_data: bool = False
    sends_data_external: bool = False


class PluginManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_version: int = Field(ge=1, le=1)
    id: str
    name: str
    version: str
    entrypoint: str
    plugin_type: PluginType
    risk_level: RiskLevel
    capabilities: dict[str, CapabilityDeclaration] = Field(default_factory=dict)
    operations: dict[str, PluginOperation] = Field(default_factory=dict)
    hooks: list[str] = Field(default_factory=list)
    background_tasks: list[str] = Field(default_factory=list)
    data_policy: PluginDataPolicy = Field(default_factory=PluginDataPolicy)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if re.fullmatch(r"[a-z0-9]+(?:[._-][a-z0-9]+)+", value) is None:
            raise ValueError("plugin id must be a reverse-domain style identifier")
        return value

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if (
            re.fullmatch(
                r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)",
                value,
            )
            is None
        ):
            raise ValueError("plugin version must be semantic major.minor.patch")
        return value

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str) -> str:
        if re.fullmatch(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*", value) is None:
            raise ValueError("entrypoint must be an importable module name")
        return value
