"""Read-only behavior simulation contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from living_agent.interaction.momentum import ConversationMomentum
from living_agent.models.conversation import TurnDecision
from living_agent.models.events import TrustedEvent


class SimulatedTaskStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    handler: str
    capability: str
    operation: str
    requires_confirmation: bool


class BehaviorSimulation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: TrustedEvent
    turn: TurnDecision
    momentum: ConversationMomentum
    context_sections: list[str]
    task_goal: str | None = None
    task_steps: list[SimulatedTaskStep] = Field(default_factory=list)
    would_call_model: bool
    would_execute_tools: bool
    persisted: bool = False
    effects_executed: bool = False
