"""Task lifecycle integration for psyche state and owner confirmation."""

from __future__ import annotations

from living_agent.audit.service import AuditService
from living_agent.execution.contracts import (
    TaskPlanProposal,
    TaskReport,
    TaskRun,
    TaskRunStatus,
    TaskStepStatus,
)
from living_agent.execution.kernel import TaskKernel
from living_agent.execution.repository import TaskRepository
from living_agent.models.events import AuthorityLevel
from living_agent.models.psyche import ActivityStatus
from living_agent.psyche.service import PsycheService
from living_agent.trust.authority import AuthorityResolver


class TaskConfirmationDeniedError(PermissionError):
    pass


class TaskService:
    def __init__(
        self,
        *,
        kernel: TaskKernel,
        repository: TaskRepository,
        psyche: PsycheService,
        authority: AuthorityResolver,
        audit: AuditService,
    ) -> None:
        self._kernel = kernel
        self._repository = repository
        self._psyche = psyche
        self._authority = authority
        self._audit = audit

    async def initialize(self) -> None:
        for run in await self._repository.recoverable_runs():
            try:
                recovered = await self._kernel.recover(run)
                await self._finish_activity_if_terminal(recovered)
            except Exception as exc:
                await self._audit.append(
                    action="task.recovery_failed",
                    actor_id="living-agent",
                    conversation_id=run.conversation_id,
                    outcome="failure",
                    details={
                        "task_id": run.task.task_id,
                        "error_code": type(exc).__name__,
                    },
                )
        terminal = await self._repository.terminal_runs_with_activities()
        activity_ids = [run.activity_id for run in terminal if run.activity_id is not None]
        activities = {
            activity.activity_id: activity
            for activity in await self._psyche.activities_by_ids(activity_ids)
        }
        for run in terminal:
            activity = activities.get(run.activity_id or "")
            if activity is not None and activity.status is ActivityStatus.RUNNING:
                await self._finish_activity_if_terminal(run)

    async def submit(self, proposal: TaskPlanProposal) -> TaskRun:
        handlers = {step.action.handler for step in proposal.plan.steps}
        if handlers == {"calculator"}:
            activity_kind = "calculator_task"
        elif handlers.intersection(
            {
                "workspace_read",
                "workspace_list",
                "workspace_search",
                "workspace_write",
                "web_fetch",
                "web_search",
                "daily_plan_read",
                "daily_plan_write",
                "daily_plan_update",
            }
        ):
            activity_kind = "work_task"
        else:
            activity_kind = "executive_task"
        activity = await self._psyche.start_activity(
            kind=activity_kind,
            summary=f"Executing task {proposal.task.task_id}.",
            source_event_ids=proposal.plan.steps[0].action.capability_request.source_event_ids,
        )
        try:
            run = await self._kernel.submit(proposal, activity_id=activity.activity_id)
        except Exception:
            await self._psyche.finish_activity(
                activity.activity_id,
                success=False,
                evidence_ids=[],
            )
            raise
        await self._finish_activity_if_terminal(run)
        return run

    async def confirm(
        self,
        *,
        task_id: str | None,
        conversation_id: str | None,
        actor_id: str,
    ) -> TaskRun:
        if self._authority.resolve(actor_id, authenticated=True) is not AuthorityLevel.OWNER:
            await self._audit.append(
                action="permission.denied",
                actor_id=actor_id,
                conversation_id=conversation_id,
                outcome="DENY",
                details={"reason_code": "task_confirmation_owner_required"},
            )
            raise TaskConfirmationDeniedError("owner authority required for task confirmation")
        run = await self._kernel.confirm(
            task_id=task_id,
            conversation_id=conversation_id,
            confirmed_by=actor_id,
        )
        await self._finish_activity_if_terminal(run)
        return run

    async def get(self, task_id: str) -> TaskRun:
        return await self._repository.get(task_id)

    async def list(
        self,
        *,
        status: TaskRunStatus | None,
        limit: int,
    ) -> list[TaskRun]:
        return await self._repository.list_runs(status=status, limit=limit)

    async def report(self, task_id: str) -> TaskReport:
        return await self._repository.get_report(task_id)

    async def cancel(self, *, task_id: str, actor_id: str) -> TaskRun:
        if self._authority.resolve(actor_id, authenticated=True) is not AuthorityLevel.OWNER:
            raise TaskConfirmationDeniedError("owner authority required for task cancellation")
        run = await self._kernel.cancel(task_id)
        await self._finish_activity_if_terminal(run)
        return run

    async def _finish_activity_if_terminal(self, run: TaskRun) -> None:
        if run.activity_id is None or run.status not in {
            TaskRunStatus.COMPLETED,
            TaskRunStatus.FAILED,
            TaskRunStatus.CANCELLED,
        }:
            return
        evidence_ids = [
            f"{run.task.task_id}:{item.step_id}"
            for item in run.step_results
            if item.status is TaskStepStatus.COMPLETED
        ]
        await self._psyche.finish_activity(
            run.activity_id,
            success=run.status is TaskRunStatus.COMPLETED,
            evidence_ids=evidence_ids,
        )
