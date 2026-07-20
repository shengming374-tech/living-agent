"""Structured Executive Cognition; this module cannot emit user-facing prose."""

from living_agent.execution.contracts import TaskConfirmationCommand, TaskPlanProposal
from living_agent.execution.planner import TaskPlanner
from living_agent.models.events import TrustedEvent


class ExecutiveCognition:
    def __init__(self, planner: TaskPlanner | None = None) -> None:
        self._planner = planner or TaskPlanner()

    def propose(self, event: TrustedEvent) -> TaskPlanProposal | None:
        return self._planner.propose(event)

    def confirmation(self, event: TrustedEvent) -> TaskConfirmationCommand | None:
        return self._planner.confirmation(event.content)
