"""Present verified task and agent outcomes through the shared social persona."""

from __future__ import annotations

from typing import Any

from living_agent.agent.contracts import AgentRun
from living_agent.audit.service import AuditService
from living_agent.cognition.context_compiler import ContextCompiler
from living_agent.cognition.model_calls import ModelCalls
from living_agent.cognition.social import SocialCognition
from living_agent.execution.contracts import TaskRun, TaskRunStatus, TaskStepStatus
from living_agent.execution.service import TaskService
from living_agent.models.conversation import TurnDecision
from living_agent.models.events import TrustedEvent
from living_agent.providers.llm import LLMProviderError

_SYNTHESIS_HANDLERS = frozenset({
    "workspace_read", "workspace_list", "workspace_search", "web_fetch", "web_search",
    "daily_plan_read",
})


class OutcomePresenter:
    def __init__(
        self, *, compiler: ContextCompiler, models: ModelCalls, social: SocialCognition,
        tasks: TaskService, audit: AuditService, root_policy: str,
    ) -> None:
        self._compiler = compiler
        self._models = models
        self._social = social
        self._tasks = tasks
        self._audit = audit
        self._root_policy = root_policy

    async def task(
        self, run: TaskRun, event: TrustedEvent, turn: TurnDecision,
        *, history: list[dict[str, Any]], psyche: dict[str, Any], synthesize: bool,
    ) -> str:
        fallback = self._social.render_task_run(run)
        if not synthesize or run.status is not TaskRunStatus.COMPLETED or not any(
            step.action.handler in _SYNTHESIS_HANDLERS for step in run.plan.steps
        ):
            return fallback
        current = {
            "task_id": run.task.task_id, "goal": run.task.goal, "status": run.status.value,
            "steps": [
                {"title": step.title, "handler": step.action.handler,
                 "status": next((result.status.value for result in run.step_results
                                 if result.step_id == step.step_id), "pending")}
                for step in run.plan.steps
            ],
        }
        return await self._synthesize(
            [run], event, turn, current=current, history=history, psyche=psyche,
            fallback=fallback, phase="task_result_synthesis",
        )

    async def agent(
        self, run: AgentRun, event: TrustedEvent, turn: TurnDecision,
        *, history: list[dict[str, Any]], psyche: dict[str, Any],
    ) -> str:
        # Controls and pending operations remain exact host-authored language.
        # / 待确认操作与控制指令保留宿主原文。
        if run.status != "completed":
            return self._social.render_agent_run(run)
        children = [await self._tasks.get(item.task_id) for item in run.observations]
        children = [child for child in children if child.conversation_id == event.conversation_id]
        fallback = self._social.render_agent_outcome(run, children)
        return await self._synthesize(
            children, event, turn,
            current={"run_id": run.run_id, "goal": run.goal, "status": run.status,
                     "iterations": run.iterations},
            history=history, psyche=psyche, fallback=fallback,
            phase="agent_result_synthesis",
            planner_summary=run.summary,
        )

    async def _synthesize(
        self, runs: list[TaskRun], event: TrustedEvent, turn: TurnDecision,
        *, current: dict[str, Any], history: list[dict[str, Any]], psyche: dict[str, Any],
        fallback: str, phase: str, planner_summary: str | None = None,
    ) -> str:
        tool_results: list[dict[str, Any]] = []
        tool_audit_ids: set[str] = set()
        activity_ids: set[str] = set()
        if planner_summary:
            # An executive answer is model output, never a verified action record.
            # / 执行层结论仍是模型输出, 不能充当已执行的证据。
            tool_results.append({
                "handler": "executive_summary", "output": {"summary": planner_summary},
                "source_event_ids": [event.event_id], "taint_labels": ["model_output"],
            })
        for run in runs:
            if run.status is TaskRunStatus.COMPLETED and run.activity_id is not None:
                activity_ids.add(run.activity_id)
            steps = {step.step_id: step for step in run.plan.steps}
            for result in run.step_results:
                if result.status is not TaskStepStatus.COMPLETED or result.output is None:
                    continue
                tool_results.append({
                    "handler": steps[result.step_id].action.handler, "output": result.output,
                    "source_event_ids": run.source_event_ids,
                    "taint_labels": result.output.get("taint_labels", ["untrusted_tool_result"]),
                })
                for result_evidence in result.evidence:
                    audit_id = result_evidence.data.get("tool_audit_id")
                    if isinstance(audit_id, str):
                        tool_audit_ids.add(audit_id)
        context = self._compiler.compile(
            event, root_policy=self._root_policy, current_task=current,
            tool_results=tool_results,
            available_capabilities=sorted({cap for run in runs
                                          for cap in run.task.allowed_capabilities}),
            conversation_history=history, psyche_state=psyche,
            interaction_plan={
                "mode": turn.mode, "expected_units_min": turn.expected_units_min,
                "expected_units_max": turn.expected_units_max, "task_result": True,
                "format": "plain_text_grounded_in_tool_results",
            },
        )
        try:
            response = await self._models.generate(context, event, phase=phase)
        except LLMProviderError:
            return fallback
        evidence = response.claim_evidence.model_copy(update={
            "activity_ids": sorted(set(response.claim_evidence.activity_ids) | activity_ids),
            "tool_audit_ids": sorted(set(response.claim_evidence.tool_audit_ids) | tool_audit_ids),
        })
        if not await self._models.approve(response.text, evidence, event, phase=phase):
            return self._social.render_continuity_block()
        await self._audit.append(
            action="response.generated", actor_id="living-agent",
            conversation_id=event.conversation_id, outcome="success",
            details={
                "event_id": event.event_id, "provider": response.provider,
                "context_sections": [section.kind.value for section in context.sections],
                **{key: current[key] for key in ("task_id", "run_id") if key in current},
            },
        )
        return self._social.render_model_text(response.text)
