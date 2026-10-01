"""确定性任务的会话编排。 / Conversation routing for deterministic task commands."""

from dataclasses import dataclass
from typing import Literal

from living_agent.cognition.executive import ExecutiveCognition
from living_agent.execution.contracts import TaskRun
from living_agent.execution.repository import TaskNotFoundError, TaskStateError
from living_agent.execution.service import TaskConfirmationDeniedError, TaskService
from living_agent.models.events import TrustedEvent


@dataclass(frozen=True)
class TaskConversationResult:
    run: TaskRun | None = None
    error: Literal["denied", "missing"] | None = None
    synthesize: bool = False


class TaskConversation:
    def __init__(self, executive: ExecutiveCognition, tasks: TaskService) -> None:
        self._executive = executive
        self._tasks = tasks

    async def handle(self, event: TrustedEvent) -> TaskConversationResult | None:
        actor = event.source_identity or "anonymous"
        try:
            confirmation = self._executive.confirmation(event)
            if confirmation is not None:
                run = await self._tasks.confirm(
                    task_id=confirmation.task_id,
                    conversation_id=event.conversation_id,
                    actor_id=actor,
                )
                return TaskConversationResult(run=run)
            cancellation = self._executive.cancellation(event)
            if cancellation is not None:
                run = await self._tasks.cancel(
                    task_id=cancellation.task_id,
                    conversation_id=event.conversation_id,
                    actor_id=actor,
                )
                return TaskConversationResult(run=run)
            status = self._executive.status(event)
            if status is not None:
                run = await self._tasks.status(
                    task_id=status.task_id,
                    conversation_id=event.conversation_id,
                    actor_id=actor,
                )
                return TaskConversationResult(run=run)
        except TaskConfirmationDeniedError:
            return TaskConversationResult(error="denied")
        except (TaskNotFoundError, TaskStateError):
            return TaskConversationResult(error="missing")
        proposal = self._executive.propose(event)
        if proposal is None:
            return None
        return TaskConversationResult(run=await self._tasks.submit(proposal), synthesize=True)
