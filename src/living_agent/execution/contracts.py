"""Executable calculator slice contracts."""

from __future__ import annotations

import math
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from living_agent.models.capabilities import CapabilityRequest
from living_agent.models.tasks import TaskContract

CALCULATOR_CAPABILITY = "calculator.evaluate"
CALCULATOR_SCOPE = "calculator/arithmetic"
CALCULATOR_PLUGIN_ID = "com.livingagent.calculator"

_CALCULATION_REQUEST = re.compile(
    r"^\s*(?:calculate|calc|compute|计算)\s*[:：]?\s*(?P<expression>.+?)\s*[?？]?\s*$",  # noqa: RUF001
    re.IGNORECASE,
)


def extract_calculation_expression(content: str | dict[str, Any]) -> str | None:
    text = content if isinstance(content, str) else str(content.get("text", ""))
    match = _CALCULATION_REQUEST.match(text)
    if match is None:
        return None
    expression = match.group("expression").strip()
    return expression or None


class CalculatorArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str = Field(min_length=1, max_length=200)

    @field_validator("expression")
    @classmethod
    def strip_expression(cls, value: str) -> str:
        return value.strip()


class CalculatorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str
    value: int | float

    @field_validator("value")
    @classmethod
    def require_finite_value(cls, value: int | float) -> int | float:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("calculator result must be finite")
        return value


class ExecutiveProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: TaskContract
    capability_request: CapabilityRequest
    plugin_id: str
    plugin_operation: str


class TaskEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    source: str
    data: dict[str, Any]


class VerifiedTaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    success: bool
    output: dict[str, Any] | None = None
    evidence: list[TaskEvidence] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
