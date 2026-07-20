"""Executable calculator slice contracts."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class TaskRunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlannedAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handler: Literal["calculator", "task_report"]
    capability_request: CapabilityRequest
    plugin_id: str | None = None
    plugin_operation: str | None = None

    @model_validator(mode="after")
    def validate_handler_metadata(self) -> PlannedAction:
        plugin_fields = (self.plugin_id, self.plugin_operation)
        if self.handler == "calculator" and any(value is None for value in plugin_fields):
            raise ValueError("calculator actions require plugin metadata")
        if self.handler == "task_report" and any(value is not None for value in plugin_fields):
            raise ValueError("host task-report actions cannot declare plugin metadata")
        return self


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(default_factory=lambda: str(uuid4()))
    title: str = Field(min_length=1, max_length=200)
    action: PlannedAction
    depends_on: list[str] = Field(default_factory=list, max_length=16)
    max_attempts: int = Field(default=2, ge=1, le=3)


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    steps: list[PlanStep] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def validate_topological_order(self) -> ExecutionPlan:
        seen: set[str] = set()
        for step in self.steps:
            if step.step_id in seen:
                raise ValueError("execution plan step IDs must be unique")
            if len(step.depends_on) != len(set(step.depends_on)):
                raise ValueError("execution plan dependencies cannot contain duplicates")
            if not set(step.depends_on).issubset(seen):
                raise ValueError("execution plan dependencies must reference earlier steps")
            seen.add(step.step_id)
        return self


class TaskPlanProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: TaskContract
    plan: ExecutionPlan

    @model_validator(mode="after")
    def validate_task_binding(self) -> TaskPlanProposal:
        if self.plan.task_id != self.task.task_id:
            raise ValueError("execution plan must be bound to its task contract")
        return self


class TaskStepResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_id: str
    status: TaskStepStatus = TaskStepStatus.PENDING
    attempts: int = Field(default=0, ge=0, le=3)
    output: dict[str, Any] | None = None
    evidence: list[TaskEvidence] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    confirmation_request_id: str | None = None


class TaskRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: TaskContract
    plan: ExecutionPlan
    status: TaskRunStatus = TaskRunStatus.PLANNED
    step_results: list[TaskStepResult]
    conversation_id: str | None = None
    source_event_ids: list[str]
    taint_labels: set[str] = Field(default_factory=set)
    pending_step_id: str | None = None
    activity_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    version: int = Field(default=1, ge=1)


class TaskConfirmationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str | None = None


class TaskReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str
    task_id: str
    content: str = Field(min_length=1, max_length=8000)
    created_by: str
    source_event_ids: list[str]
    created_at: datetime
