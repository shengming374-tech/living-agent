"""Structured task contracts owned by Executive Cognition."""

from __future__ import annotations

from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(default_factory=lambda: str(uuid4()))
    requester_id: str
    goal: str
    constraints: list[str]
    allowed_capabilities: list[str]
    forbidden_operations: list[str]
    success_criteria: list[str]
    confirmation_requirements: list[str]

    @field_validator("requester_id", "goal")
    @classmethod
    def require_nonempty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("task requester and goal cannot be empty")
        return normalized

    @field_validator(
        "constraints",
        "allowed_capabilities",
        "forbidden_operations",
        "success_criteria",
        "confirmation_requirements",
    )
    @classmethod
    def normalize_string_list(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value if item.strip()]
        if len(normalized) != len(set(normalized)):
            raise ValueError("task contract lists cannot contain duplicate values")
        return normalized
