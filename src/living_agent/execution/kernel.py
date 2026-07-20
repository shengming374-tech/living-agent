"""Persistent multi-step task execution, recovery, and verification."""

from __future__ import annotations

import asyncio
from typing import Protocol

from living_agent.audit.service import AuditService
from living_agent.evaluation.task_verifier import TaskPlanVerifier
from living_agent.execution.contracts import (
    ExecutiveProposal,
    TaskPlanProposal,
    TaskRun,
    TaskRunStatus,
    TaskStepResult,
    TaskStepStatus,
    VerifiedTaskResult,
)
from living_agent.execution.report import TaskReportExecutor
from living_agent.execution.repository import TaskRepository, TaskStateError

_RETRYABLE_ERRORS = frozenset({"plugin_timeout", "plugin_crashed", "plugin_protocol_error"})


class CalculatorExecutor(Protocol):
    async def execute(self, proposal: ExecutiveProposal) -> VerifiedTaskResult: ...


class TaskPlanValidationError(ValueError):
    pass


class TaskKernel:
    def __init__(
        self,
        *,
        repository: TaskRepository,
        calculator: CalculatorExecutor,
        reports: TaskReportExecutor,
        verifier: TaskPlanVerifier,
        audit: AuditService,
    ) -> None:
        self._repository = repository
        self._calculator = calculator
        self._reports = reports
        self._verifier = verifier
        self._audit = audit
        self._run_lock = asyncio.Lock()

    async def submit(
        self,
        proposal: TaskPlanProposal,
        *,
        activity_id: str | None,
    ) -> TaskRun:
        validation_errors = self._verifier.validate(proposal)
        if validation_errors:
            await self._audit.append(
                action="task.plan_rejected",
                actor_id=proposal.task.requester_id,
                outcome="rejected",
                details={
                    "task_id": proposal.task.task_id,
                    "reason_codes": validation_errors,
                },
            )
            raise TaskPlanValidationError(", ".join(validation_errors))
        async with self._run_lock:
            run = await self._repository.create(proposal, activity_id=activity_id)
            await self._audit.append(
                action="task.created",
                actor_id=run.task.requester_id,
                conversation_id=run.conversation_id,
                outcome="planned",
                details={
                    "task_id": run.task.task_id,
                    "plan_id": run.plan.plan_id,
                    "step_count": len(run.plan.steps),
                    "allowed_capabilities": run.task.allowed_capabilities,
                },
            )
            return await self._execute(run, confirmed_by=None)

    async def confirm(
        self,
        *,
        task_id: str | None,
        conversation_id: str | None,
        confirmed_by: str,
    ) -> TaskRun:
        async with self._run_lock:
            run = (
                await self._repository.get(task_id)
                if task_id is not None
                else await self._repository.latest_waiting(conversation_id)
            )
            if run.status is not TaskRunStatus.WAITING_CONFIRMATION:
                raise TaskStateError("task is not waiting for confirmation")
            if conversation_id is not None and run.conversation_id != conversation_id:
                raise TaskStateError("task confirmation belongs to another conversation")
            return await self._execute(run, confirmed_by=confirmed_by)

    async def recover(self, run: TaskRun) -> TaskRun:
        async with self._run_lock:
            if run.status not in {TaskRunStatus.PLANNED, TaskRunStatus.RUNNING}:
                raise TaskStateError("only planned or running tasks can be recovered")
            results = list(run.step_results)
            for index, result in enumerate(results):
                if result.status is not TaskStepStatus.RUNNING:
                    continue
                step = next(item for item in run.plan.steps if item.step_id == result.step_id)
                if step.action.handler == "task_report":
                    waiting = result.model_copy(
                        update={
                            "status": TaskStepStatus.WAITING_CONFIRMATION,
                            "attempts": max(0, result.attempts - 1),
                            "errors": ["confirmation_required_after_restart"],
                            "confirmation_request_id": (step.action.capability_request.request_id),
                        }
                    )
                    results[index] = waiting
                    run = run.model_copy(update={"step_results": results})
                    recovered = await self._save_state(
                        run,
                        status=TaskRunStatus.WAITING_CONFIRMATION,
                        pending_step_id=step.step_id,
                    )
                    await self._audit_recovery(recovered, "write_reconfirmation_required")
                    return recovered
                if result.attempts >= step.max_attempts:
                    results[index] = result.model_copy(
                        update={
                            "status": TaskStepStatus.FAILED,
                            "errors": ["interrupted_after_final_attempt"],
                        }
                    )
                    run = run.model_copy(update={"step_results": results})
                    failed = await self._fail(run)
                    await self._audit_recovery(failed, "attempts_exhausted")
                    return failed
                results[index] = result.model_copy(
                    update={
                        "status": TaskStepStatus.PENDING,
                        "errors": ["interrupted_at_restart"],
                    }
                )
            run = run.model_copy(update={"step_results": results})
            recovered = await self._execute(run, confirmed_by=None)
            await self._audit_recovery(recovered, "execution_resumed")
            return recovered

    async def cancel(self, task_id: str) -> TaskRun:
        async with self._run_lock:
            run = await self._repository.get(task_id)
            if run.status in {
                TaskRunStatus.COMPLETED,
                TaskRunStatus.FAILED,
                TaskRunStatus.CANCELLED,
            }:
                raise TaskStateError("terminal task cannot be cancelled")
            results = [
                result.model_copy(
                    update={
                        "status": TaskStepStatus.SKIPPED,
                        "errors": ["task_cancelled"],
                        "confirmation_request_id": None,
                    }
                )
                if result.status
                in {
                    TaskStepStatus.PENDING,
                    TaskStepStatus.RUNNING,
                    TaskStepStatus.WAITING_CONFIRMATION,
                }
                else result
                for result in run.step_results
            ]
            cancelled = await self._save_state(
                run.model_copy(update={"step_results": results}),
                status=TaskRunStatus.CANCELLED,
                pending_step_id=None,
            )
            await self._audit.append(
                action="task.cancelled",
                actor_id="living-agent",
                conversation_id=cancelled.conversation_id,
                outcome="cancelled",
                details={"task_id": cancelled.task.task_id},
            )
            return cancelled

    async def _execute(self, run: TaskRun, *, confirmed_by: str | None) -> TaskRun:
        run = await self._save_state(
            run,
            status=TaskRunStatus.RUNNING,
            pending_step_id=None,
        )
        confirmation = confirmed_by
        for step in run.plan.steps:
            current = self._result(run, step.step_id)
            if current.status is TaskStepStatus.COMPLETED:
                continue
            if not self._dependencies_completed(run, step.depends_on):
                failed = current.model_copy(
                    update={
                        "status": TaskStepStatus.SKIPPED,
                        "errors": ["dependency_failed"],
                        "confirmation_request_id": None,
                    }
                )
                run = await self._save_result(run, failed)
                return await self._fail(run)

            while current.attempts < step.max_attempts:
                current = current.model_copy(
                    update={
                        "status": TaskStepStatus.RUNNING,
                        "attempts": current.attempts + 1,
                        "errors": [],
                        "confirmation_request_id": None,
                    }
                )
                run = await self._save_result(run, current)
                await self._audit.append(
                    action="task.step_started",
                    actor_id=run.task.requester_id,
                    conversation_id=run.conversation_id,
                    outcome="running",
                    details={
                        "task_id": run.task.task_id,
                        "step_id": step.step_id,
                        "handler": step.action.handler,
                        "attempt": current.attempts,
                    },
                )
                executed = await self._execute_step(
                    run,
                    step_id=step.step_id,
                    confirmed_by=confirmation,
                )
                current = executed.model_copy(
                    update={"step_id": step.step_id, "attempts": current.attempts}
                )
                if current.status is TaskStepStatus.WAITING_CONFIRMATION:
                    current = current.model_copy(update={"attempts": current.attempts - 1})
                run = await self._save_result(run, current)

                if current.status is TaskStepStatus.WAITING_CONFIRMATION:
                    await self._audit.append(
                        action="task.waiting_confirmation",
                        actor_id=run.task.requester_id,
                        conversation_id=run.conversation_id,
                        outcome="waiting",
                        details={
                            "task_id": run.task.task_id,
                            "step_id": step.step_id,
                            "request_id": current.confirmation_request_id,
                        },
                    )
                    return await self._save_state(
                        run,
                        status=TaskRunStatus.WAITING_CONFIRMATION,
                        pending_step_id=step.step_id,
                    )
                if current.status is TaskStepStatus.COMPLETED:
                    confirmation = None
                    await self._audit.append(
                        action="task.step_completed",
                        actor_id=run.task.requester_id,
                        conversation_id=run.conversation_id,
                        outcome="verified",
                        details={
                            "task_id": run.task.task_id,
                            "step_id": step.step_id,
                            "evidence_count": len(current.evidence),
                            "attempts": current.attempts,
                        },
                    )
                    break
                if not set(current.errors).intersection(_RETRYABLE_ERRORS):
                    return await self._fail(run)
                if current.attempts < step.max_attempts:
                    await self._audit.append(
                        action="task.step_retry",
                        actor_id=run.task.requester_id,
                        conversation_id=run.conversation_id,
                        outcome="retrying",
                        details={
                            "task_id": run.task.task_id,
                            "step_id": step.step_id,
                            "attempt": current.attempts,
                            "error_codes": current.errors,
                        },
                    )
            if current.status is not TaskStepStatus.COMPLETED:
                return await self._fail(run)

        verification_errors = self._verifier.verify_completion(run)
        if verification_errors:
            await self._audit.append(
                action="task.verification_failed",
                actor_id=run.task.requester_id,
                conversation_id=run.conversation_id,
                outcome="rejected",
                details={"task_id": run.task.task_id, "reason_codes": verification_errors},
            )
            return await self._fail(run)
        completed = await self._save_state(
            run,
            status=TaskRunStatus.COMPLETED,
            pending_step_id=None,
        )
        await self._audit_completion(completed)
        return completed

    async def _execute_step(
        self,
        run: TaskRun,
        *,
        step_id: str,
        confirmed_by: str | None,
    ) -> TaskStepResult:
        step = next(item for item in run.plan.steps if item.step_id == step_id)
        if step.action.handler == "calculator":
            result = await self._calculator.execute(
                ExecutiveProposal(
                    task=run.task,
                    capability_request=step.action.capability_request,
                    plugin_id=step.action.plugin_id or "",
                    plugin_operation=step.action.plugin_operation or "",
                )
            )
            return TaskStepResult(
                step_id=step_id,
                status=(TaskStepStatus.COMPLETED if result.success else TaskStepStatus.FAILED),
                output=result.output,
                evidence=result.evidence,
                errors=result.errors,
            )
        return await self._reports.execute(
            task=run.task,
            action=step.action,
            prior_results=run.step_results,
            confirmed_by=confirmed_by,
        )

    async def _fail(self, run: TaskRun) -> TaskRun:
        results = []
        for result in run.step_results:
            if result.status is TaskStepStatus.PENDING:
                result = result.model_copy(
                    update={"status": TaskStepStatus.SKIPPED, "errors": ["task_failed"]}
                )
            results.append(result)
        run = run.model_copy(update={"step_results": results})
        failed = await self._save_state(
            run,
            status=TaskRunStatus.FAILED,
            pending_step_id=None,
        )
        await self._audit_completion(failed)
        return failed

    async def _audit_completion(self, run: TaskRun) -> None:
        await self._audit.append(
            action="task.completed",
            actor_id="living-agent",
            conversation_id=run.conversation_id,
            outcome="success" if run.status is TaskRunStatus.COMPLETED else "failure",
            details={
                "task_id": run.task.task_id,
                "status": run.status.value,
                "step_count": len(run.step_results),
                "evidence_count": sum(len(item.evidence) for item in run.step_results),
                "error_codes": sorted(
                    {error for item in run.step_results for error in item.errors}
                ),
            },
        )

    async def _audit_recovery(self, run: TaskRun, reason_code: str) -> None:
        await self._audit.append(
            action="task.recovered",
            actor_id="living-agent",
            conversation_id=run.conversation_id,
            outcome=run.status.value,
            details={"task_id": run.task.task_id, "reason_code": reason_code},
        )

    async def _save_state(
        self,
        run: TaskRun,
        *,
        status: TaskRunStatus,
        pending_step_id: str | None,
    ) -> TaskRun:
        return await self._repository.save(
            run.model_copy(update={"status": status, "pending_step_id": pending_step_id})
        )

    async def _save_result(self, run: TaskRun, result: TaskStepResult) -> TaskRun:
        results = [result if item.step_id == result.step_id else item for item in run.step_results]
        return await self._repository.save(run.model_copy(update={"step_results": results}))

    @staticmethod
    def _result(run: TaskRun, step_id: str) -> TaskStepResult:
        return next(item for item in run.step_results if item.step_id == step_id)

    @staticmethod
    def _dependencies_completed(run: TaskRun, dependencies: list[str]) -> bool:
        results = {item.step_id: item.status for item in run.step_results}
        return all(results.get(item) is TaskStepStatus.COMPLETED for item in dependencies)
