"""Evidence proposed alongside user-visible continuity claims."""

from pydantic import BaseModel, ConfigDict, Field


class ClaimEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_ids: list[str] = Field(default_factory=list)
    thought_record_ids: list[str] = Field(default_factory=list)
    activity_ids: list[str] = Field(default_factory=list)
    tool_audit_ids: list[str] = Field(default_factory=list)
    viewpoint_version_ids: list[str] = Field(default_factory=list)
