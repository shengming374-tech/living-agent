"""Structured Executive Cognition; this module cannot emit user-facing prose."""

from living_agent.execution.contracts import (
    TaskCancellationCommand,
    TaskConfirmationCommand,
    TaskPlanProposal,
    TaskStatusCommand,
)
from living_agent.execution.planner import TaskPlanner
from living_agent.models.events import TrustedEvent


class ExecutiveCognition:
    def __init__(self, planner: TaskPlanner | None = None) -> None:
        self._planner = planner or TaskPlanner()

    def propose(self, event: TrustedEvent) -> TaskPlanProposal | None:
        return self._planner.propose(event)

    def confirmation(self, event: TrustedEvent) -> TaskConfirmationCommand | None:
        return self._planner.confirmation(event.content)

    def cancellation(self, event: TrustedEvent) -> TaskCancellationCommand | None:
        return self._planner.cancellation(event.content)

    def status(self, event: TrustedEvent) -> TaskStatusCommand | None:
        return self._planner.status(event.content)
