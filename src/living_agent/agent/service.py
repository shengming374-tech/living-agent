"""观察、决策、行动与恢复。 / Observe, decide, act and checkpoint."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable
from typing import Protocol

from pydantic import ValidationError

from living_agent.agent.contracts import AgentDecision, AgentObservation, AgentRun
from living_agent.agent.repository import AgentConflictError, AgentRepository
from living_agent.agent.tools import compile_action
from living_agent.audit.service import AuditService
from living_agent.execution.contracts import TaskRun, TaskRunStatus
from living_agent.execution.repository import TaskNotFoundError, TaskStateError
from living_agent.execution.service import TaskService
from living_agent.execution.tool_catalog import TOOL_CATALOG
from living_agent.models.events import AuthorityLevel, SourceType, TrustedEvent
from living_agent.providers.llm import LLMProviderError
from living_agent.trust.authority import AuthorityResolver
from living_agent.trust.taint import TaintLabel


class DecisionPlanner(Protocol):
    async def decide(self, run: AgentRun) -> AgentDecision: ...


class AgentService:
    def __init__(
        self,
        *,
        repository: AgentRepository,
        planner: DecisionPlanner,
        tasks: TaskService,
        audit: AuditService,
        authority: AuthorityResolver,
        max_iterations: int = 8,
        decision_timeout: float = 90,
        enabled: bool = True,
    ) -> None:
        self.repository = repository
        self._planner = planner
        self._tasks = tasks
        self._audit = audit
        self._authority = authority
        self._max_iterations = max_iterations
        self._decision_timeout = decision_timeout
        self._drivers: dict[str, asyncio.Task[object]] = {}
        self.enabled = enabled

    async def initialize(self) -> None:
        # Startup never makes fresh model decisions. / 启动只暂停, 不自动调用模型。
        for run in await self.repository.running():
            run.status = "paused"
            run.error_code = "interrupted_at_restart"
            await self.repository.save(run)

    def authorize(self, event: TrustedEvent) -> None:
        if not self.enabled:
            raise AgentConflictError("agent is disabled")
        if (
            event.source_type not in {SourceType.DIRECT_MESSAGE, SourceType.GROUP_MESSAGE}
            or event.authority_level not in {AuthorityLevel.OWNER, AuthorityLevel.ADMIN}
            or not event.source_identity
            or self._authority.resolve(event.source_identity, authenticated=True)
            not in {AuthorityLevel.OWNER, AuthorityLevel.ADMIN}
            or TaintLabel.SUSPECTED_INSTRUCTION.value in event.taint_labels
        ):
            raise PermissionError("trusted social requester required")

    async def start(self, event: TrustedEvent, goal: str) -> AgentRun:
        self.authorize(event)
        run = await self.repository.create(
            AgentRun(
                goal=goal.strip(),
                event=event,
                max_iterations=self._max_iterations,
            )
        )
        return await self._drive(run, lifecycle="started")

    async def resume(
        self, run_id: str, *, actor_id: str, message: str | None = None, confirm: bool = False
    ) -> AgentRun:
        if run_id in self._drivers:
            raise AgentConflictError("agent run is already being driven")
        run = await self.repository.get(run_id)
        self._owner(actor_id)
        self.authorize(run.event)
        if run.status not in {"paused", "waiting_input", "waiting_confirmation"}:
            raise AgentConflictError("agent run is not resumable")
        if confirm and (run.status != "waiting_confirmation" or run.pending_proposal is None):
            raise AgentConflictError("no exact action awaiting confirmation")
        message = message.strip() if message else None
        if run.status == "waiting_input" and not message:
            raise AgentConflictError("a response is required")
        if message:
            if len(message) > 2000:
                raise AgentConflictError("response exceeds input limit")
            if len(run.input_notes) >= 16:
                raise AgentConflictError("input limit reached")
            run.input_notes.append(message)
        run.status = "running"
        run.error_code = None
        run = await self.repository.save(run)
        return await self._drive(
            run, confirmed_by=actor_id if confirm else None, lifecycle="resumed"
        )

    async def cancel(self, run_id: str, *, actor_id: str) -> AgentRun:
        self._owner(actor_id)
        run = await self.repository.get(run_id)
        if run.status in {"completed", "failed", "cancelled"}:
            raise AgentConflictError("terminal agent run cannot be cancelled")
        run.status = "cancelled"
        run.summary = "目标已取消; 已经完成的操作保留记录"
        run = await self.repository.save(run)
        driver = self._drivers.get(run_id)
        if driver is not None and driver is not asyncio.current_task():
            driver.cancel()
        run = await self._settle_cancelled(run)
        await self._record(run, "cancelled")
        return run

    def _owner(self, actor_id: str) -> None:
        if self._authority.resolve(actor_id, authenticated=True) is not AuthorityLevel.OWNER:
            raise PermissionError("owner authority required")

    async def _drive(
        self,
        run: AgentRun,
        *,
        confirmed_by: str | None = None,
        lifecycle: str | None = None,
    ) -> AgentRun:
        driver = asyncio.current_task()
        if driver is None or run.run_id in self._drivers:
            raise AgentConflictError("agent run is already being driven")
        self._drivers[run.run_id] = driver
        try:
            if lifecycle:
                await self._record(run, lifecycle)
            while True:
                current = await self.repository.get(run.run_id)
                if current.status == "cancelled":
                    return await self._settle_cancelled(current)
                if run.pending_proposal is not None:
                    child = await self._pending_task(run, confirmed_by)
                    confirmed_by = None
                    if child.status == TaskRunStatus.WAITING_CONFIRMATION:
                        run.status = "waiting_confirmation"
                        run.summary = "下一步需要确认, 请查看确切的工具参数"
                        return await self.repository.save(run)
                    if child.status in {TaskRunStatus.RUNNING, TaskRunStatus.PLANNED}:
                        run.status = "paused"
                        run.error_code = "child_task_in_progress"
                        return await self.repository.save(run)
                    run.observations.append(self._observation(child))
                    run.pending_proposal = None
                    if child.status == TaskRunStatus.CANCELLED:
                        run.status = "cancelled"
                        run.summary = "当前操作已取消, 目标随之停止"
                        return await self.repository.save(run)
                    run = await self.repository.save(run)
                    await self._record(run, "observed")
                if run.iterations >= run.max_iterations:
                    run.status = "failed"
                    run.error_code = "iteration_budget_exhausted"
                    run.summary = "已达到本次决策上限, 目标尚未完成"
                    return await self.repository.save(run)
                # Charge before calling the model, including interrupted calls. / 先计费再决策。
                run.iterations += 1
                run = await self.repository.save(run)
                async with asyncio.timeout(self._decision_timeout):
                    decision = await self._planner.decide(run)
                run.decisions.append(decision)
                run.summary = decision.summary
                if decision.action == "ask":
                    run.status = "waiting_input"
                    run = await self.repository.save(run)
                    await self._record(run, "waiting_input")
                    return run
                if decision.action == "finish":
                    evidence = {
                        item.task_id
                        for item in run.observations
                        if item.status == "completed" and item.evidence_kinds
                    }
                    if not decision.evidence_task_ids or not set(
                        decision.evidence_task_ids
                    ).issubset(evidence):
                        raise ValueError("finish_requires_observed_evidence")
                    run.status = "completed"
                    run = await self.repository.save(run)
                    await self._record(run, "completed")
                    return run
                proposal = compile_action(run, decision)
                self._check_repetition(run)
                run.pending_proposal = proposal
                # Persist the exact child ID before effects. / 产生影响前保存精确子任务 ID。
                run = await self.repository.save(run)
                await self._record(run, "action_planned")
        except AgentConflictError:
            # A concurrent cancellation wins over stale work. / 取消优先于过期结果。
            current = await self.repository.get(run.run_id)
            if current.status == "cancelled":
                return await self._settle_cancelled(current)
            raise
        except asyncio.CancelledError:
            current = await self.repository.get(run.run_id)
            if current.status == "cancelled":
                return await self._settle_cancelled(current)
            run.status = "paused"
            run.error_code = "request_interrupted"
            try:
                await self.repository.save(run)
            except AgentConflictError:
                pass
            raise
        except Exception as exc:
            # No upstream bodies or secrets in public errors. / 不泄漏上游错误正文。
            run.status = "failed"
            run.error_code = self._error_code(exc)
            run.summary = "本次执行未完成, 请查看已保存的行动与结果"
            try:
                run = await self.repository.save(run)
            except AgentConflictError:
                return await self.repository.get(run.run_id)
            await self._record(run, "failed")
            return run
        finally:
            self._drivers.pop(run.run_id, None)

    async def _settle_cancelled(self, run: AgentRun) -> AgentRun:
        child = await self._cancel_pending_child(run)
        while True:
            current = await self.repository.get(run.run_id)
            if current.pending_proposal is None:
                return current
            if child is not None and not any(
                item.task_id == child.task.task_id for item in current.observations
            ):
                current.observations.append(self._observation(child))
            current.pending_proposal = None
            try:
                return await self.repository.save(current)
            except AgentConflictError:
                continue

    async def _cancel_pending_child(self, run: AgentRun) -> TaskRun | None:
        if run.pending_proposal is None:
            return None
        try:
            child = await self._tasks.get(run.pending_proposal.task.task_id)
            if child.status in {
                TaskRunStatus.PLANNED,
                TaskRunStatus.RUNNING,
                TaskRunStatus.WAITING_CONFIRMATION,
            }:
                child = await self._tasks.cancel(
                    task_id=child.task.task_id, actor_id=self._authority.owner_id
                )
            return child
        except TaskNotFoundError:
            return None
        except TaskStateError:
            return await self._tasks.get(run.pending_proposal.task.task_id)

    async def _pending_task(self, run: AgentRun, confirmed_by: str | None) -> TaskRun:
        assert run.pending_proposal is not None
        task_id = run.pending_proposal.task.task_id
        try:
            child = await self._tasks.get(task_id)
        except TaskNotFoundError:
            child = await self._child_call(run, self._tasks.submit(run.pending_proposal))
        if child.status in {TaskRunStatus.PLANNED, TaskRunStatus.RUNNING}:
            child = await self._tasks.recover(task_id)
        if confirmed_by and child.status == TaskRunStatus.WAITING_CONFIRMATION:
            child = await self._child_call(
                run,
                self._tasks.confirm(
                    task_id=task_id,
                    conversation_id=run.event.conversation_id,
                    actor_id=confirmed_by,
                ),
            )
        return child

    @staticmethod
    async def _child_call(run: AgentRun, call: Awaitable[TaskRun]) -> TaskRun:
        assert run.pending_proposal is not None
        handler = run.pending_proposal.plan.steps[0].action.handler
        if handler not in {"workspace_write", "daily_plan_write", "daily_plan_update"}:
            return await call
        # A file-writing thread cannot be stopped; persist its result before stopping the goal.
        pending = asyncio.ensure_future(call)
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            while not pending.done():
                try:
                    await asyncio.shield(pending)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            raise

    @staticmethod
    def _check_repetition(run: AgentRun) -> None:
        """Reject consecutive equivalent calls; changed state permits a later reread."""
        decision = run.decisions[-1]
        spec = TOOL_CATALOG[decision.tool or ""]
        signature = spec.arguments.model_validate(decision.arguments).model_dump(mode="json")
        repeats = 1
        for previous in reversed(run.decisions[:-1]):
            if previous.action != "tool" or previous.tool != decision.tool:
                break
            arguments = spec.arguments.model_validate(previous.arguments).model_dump(mode="json")
            if arguments != signature:
                break
            repeats += 1
        if repeats > 2:
            raise ValueError("repeated_action_without_progress")

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, TimeoutError):
            return "decision_timeout"
        if isinstance(exc, json.JSONDecodeError):
            return "model_response_invalid_json"
        if isinstance(exc, ValidationError):
            return "model_decision_invalid"
        if isinstance(exc, LLMProviderError):
            return "model_request_failed"
        if str(exc) in {
            "unknown_agent_tool",
            "finish_requires_observed_evidence",
            "repeated_action_without_progress",
        }:
            return str(exc)
        return type(exc).__name__

    @staticmethod
    def _observation(child: TaskRun) -> AgentObservation:
        result = child.step_results[0]
        output = result.output
        if output and len(json.dumps(output, ensure_ascii=False)) > 12000:
            output = {"truncated": True, "excerpt": json.dumps(output, ensure_ascii=False)[:12000]}
        return AgentObservation(
            task_id=child.task.task_id,
            tool=child.plan.steps[0].action.handler,
            arguments=child.plan.steps[0].action.capability_request.arguments,
            status=child.status.value,
            output=output,
            evidence_kinds=[item.kind for item in result.evidence],
            errors=result.errors,
        )

    async def _record(self, run: AgentRun, outcome: str) -> None:
        await self._audit.append(
            action="agent.lifecycle",
            actor_id=run.event.source_identity,
            conversation_id=run.event.conversation_id,
            outcome=outcome,
            details={
                "run_id": run.run_id,
                "iterations": run.iterations,
                "status": run.status,
                "error_code": run.error_code,
            },
        )
