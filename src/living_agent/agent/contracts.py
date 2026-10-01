"""宿主持有的目标与决策合同。 / Host-owned goals and decision contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from living_agent.execution.contracts import TaskPlanProposal
from living_agent.models.events import TrustedEvent

AgentStatus = Literal[
    "running", "paused", "waiting_confirmation", "waiting_input", "completed", "failed", "cancelled"
]


class AgentDecision(BaseModel):
    """Only proposals, never identity, permissions or evidence. / 仅输出提案。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["tool", "finish", "ask"]
    summary: str = Field(min_length=1, max_length=2000)
    tool: str | None = Field(default=None, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)
    evidence_task_ids: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def check_shape(self) -> AgentDecision:
        if self.action == "tool" and not self.tool:
            raise ValueError("tool decision requires a tool name")
        if self.action != "tool" and (self.tool is not None or self.arguments):
            raise ValueError("non-tool decision cannot invoke tools")
        return self


class AgentObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    status: str
    output: dict[str, Any] | None = None
    evidence_kinds: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class AgentRun(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    goal: str = Field(min_length=1, max_length=1000)
    event: TrustedEvent
    status: AgentStatus = "running"
    iterations: int = 0
    max_iterations: int = Field(default=8, ge=1, le=32)
    decisions: list[AgentDecision] = Field(default_factory=list)
    observations: list[AgentObservation] = Field(default_factory=list)
    pending_proposal: TaskPlanProposal | None = None
    input_notes: list[str] = Field(default_factory=list, max_length=16)
    summary: str = ""
    error_code: str | None = None
    version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    goal: str = Field(min_length=1, max_length=1000)
    conversation_id: str = Field(default="agent-studio", min_length=1, max_length=255)


class AgentResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str | None = Field(default=None, min_length=1, max_length=2000)
