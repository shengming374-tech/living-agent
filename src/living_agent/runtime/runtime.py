"""Coordinate trusted ingress, social scheduling and cognition handoffs."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime
from typing import Any

from living_agent.agent.conversation import AgentConversation
from living_agent.agent.repository import AgentConflictError, AgentNotFoundError
from living_agent.agent.service import AgentService
from living_agent.audit.service import AuditService
from living_agent.cognition.context_compiler import CompiledContext, ContextCompiler
from living_agent.cognition.executive import ExecutiveCognition
from living_agent.cognition.model_calls import ModelCalls
from living_agent.cognition.outcomes import OutcomePresenter
from living_agent.cognition.social import SocialCognition
from living_agent.evaluation.continuity_critic import ContinuityCritic
from living_agent.evaluation.simulator import BehaviorSimulation, SimulatedTaskStep
from living_agent.execution.conversation import TaskConversation
from living_agent.execution.service import TaskService
from living_agent.execution.work_contracts import is_work_write_handler
from living_agent.interaction.impressions import AttentionCueService, SessionImpressionService
from living_agent.interaction.momentum import ConversationMomentum
from living_agent.interaction.repository import (
    DeliveryResult,
    StoredUtterance,
)
from living_agent.interaction.scheduler import ReplyNecessityEvaluator
from living_agent.interaction.social_state import SocialStateRepository
from living_agent.interaction.utterance import UtteranceCoordinator, UtteranceTurn
from living_agent.memory.facts import RecallRoute, extract_fact, route_recall
from living_agent.memory.service import MemoryService
from living_agent.models.conversation import ChatResult, TurnDecision, TurnScheduleDecision
from living_agent.models.events import IngressEnvelope, SourceType, TrustedEvent
from living_agent.models.memory import (
    MemoryLayer,
    MemoryProbeRequest,
    MemoryProbeResponse,
)
from living_agent.providers.llm import LLMProvider, LLMProviderError
from living_agent.psyche.service import PsycheService
from living_agent.runtime.delivery import DeliveryRecorder
from living_agent.runtime.event_bus import EventBus
from living_agent.runtime.memory_probe import MemoryProbeRunner
from living_agent.storage.events import EventRepository
from living_agent.trust.boundary import TrustBoundary
from living_agent.trust.taint import TaintLabel
from living_agent.users.service import UserService


class AgentRuntime:
    def __init__(
        self,
        *,
        boundary: TrustBoundary,
        events: EventRepository,
        audit: AuditService,
        event_bus: EventBus,
        social: SocialCognition,
        executive: ExecutiveCognition,
        tasks: TaskService,
        context_compiler: ContextCompiler,
        llm: LLMProvider,
        root_policy: str,
        psyche: PsycheService,
        continuity_critic: ContinuityCritic,
        memories: MemoryService,
        users: UserService,
        utterances: UtteranceCoordinator,
        reply_necessity: ReplyNecessityEvaluator,
        social_state: SocialStateRepository,
        impressions: SessionImpressionService,
        attention: AttentionCueService,
        social_scheduler_enabled: bool,
        social_focus_idle_exit_cycles: int,
        social_cooldown_seconds: float,
        agent: AgentService | None = None,
    ) -> None:
        self._agent_conversation = AgentConversation(agent) if agent else None
        self._boundary = boundary
        self._events = events
        self._audit = audit
        self._event_bus = event_bus
        self._social = social
        self._executive = executive
        self._task_conversation = TaskConversation(executive, tasks)
        self._context_compiler = context_compiler
        self._root_policy = root_policy
        self._psyche = psyche
        self._memories = memories
        self._users = users
        self._utterances = utterances
        self._reply_necessity = reply_necessity
        self._social_state = social_state
        self._impressions = impressions
        self._attention = attention
        self._social_scheduler_enabled = social_scheduler_enabled
        self._social_focus_idle_exit_cycles = social_focus_idle_exit_cycles
        self._models = ModelCalls(llm=llm, audit=audit, critic=continuity_critic)
        self._outcomes = OutcomePresenter(
            compiler=context_compiler, models=self._models, social=social, tasks=tasks,
            audit=audit, root_policy=root_policy,
        )
        self._social_schedule_lock = asyncio.Lock()
        self._memory_probe = MemoryProbeRunner(
            boundary=boundary, compiler=context_compiler, llm=llm, memories=memories,
            audit=audit, root_policy=root_policy,
        )
        self._delivery = DeliveryRecorder(
            events=events, audit=audit, memories=memories, utterances=utterances,
            social_state=social_state, cooldown_seconds=social_cooldown_seconds,
        )

    async def _handle_agent(
        self, event: TrustedEvent, turn: TurnDecision, schedule: TurnScheduleDecision,
        *, history: list[dict[str, Any]], psyche: dict[str, Any],
        planning_turn: UtteranceTurn | None, fallback: bool = False,
    ) -> ChatResult | None:
        if self._agent_conversation is None:
            return None
        turn = turn.model_copy(update={
            "mode": "act", "reason_code": "agent_goal",
            "expected_units_min": 1, "expected_units_max": 3,
        })
        try:
            run = await self._agent_conversation.handle(event, fallback=fallback)
            if run is None:
                return None
            message = await self._outcomes.agent(
                run, event, turn, history=history, psyche=psyche,
            )
            run_id = run.run_id
        except (AgentConflictError, AgentNotFoundError, PermissionError, ValueError):
            message = "这个智能体请求暂时无法执行, 请检查目标状态与当前会话"
            run_id = None
        return await self._visible_result(
            event, turn, schedule, message, planning_turn=planning_turn, agent_run_id=run_id,
        )

    async def _visible_result(
        self, event: TrustedEvent, turn: TurnDecision, schedule: TurnScheduleDecision,
        message: str, *, planning_turn: UtteranceTurn | None,
        agent_run_id: str | None = None,
    ) -> ChatResult:
        if planning_turn is not None and not await self._utterances.turn_is_current(planning_turn):
            await self._audit.append(
                action="model.result_discarded", actor_id="living-agent",
                conversation_id=event.conversation_id, outcome="stale",
                details={"event_id": event.event_id, "generation": planning_turn.generation,
                         "reason_code": "superseded_during_planning", "phase": "execution_result"},
            )
            return ChatResult(
                event=event, turn=turn, schedule=schedule, message=None, messages=[],
                agent_run_id=agent_run_id,
            )
        utterance = self._social.plan_utterance(message, turn)
        messages = [unit.text for unit in utterance.units]
        return ChatResult(
            event=event, turn=turn, schedule=schedule, message=messages[0], messages=messages,
            utterance=utterance, agent_run_id=agent_run_id,
        )

    @property
    def root_policy_checksum(self) -> str:
        return hashlib.sha256(self._root_policy.encode("utf-8")).hexdigest()

    def compile_context_preview(
        self,
        envelope: IngressEnvelope,
        *,
        current_task: dict[str, Any] | None = None,
        available_capabilities: list[str] | None = None,
    ) -> CompiledContext:
        event = self._boundary.normalize(envelope)
        return self._context_compiler.compile(
            event,
            root_policy=self._root_policy,
            current_task=current_task,
            available_capabilities=available_capabilities,
        )

    async def probe_memory(
        self, request: MemoryProbeRequest, *, actor_id: str,
    ) -> MemoryProbeResponse:
        return await self._memory_probe.run(request, actor_id=actor_id)

    async def begin_utterance_turn(
        self,
        conversation_id: str | None,
        *,
        platform: str,
        replace_active: bool = True,
    ) -> UtteranceTurn | None:
        if conversation_id is None:
            return None
        return await self._utterances.begin_turn(
            conversation_id,
            platform=platform,
            replace_active=replace_active,
        )

    async def handle_platform_chat(
        self,
        envelope: IngressEnvelope,
        *,
        platform: str,
    ) -> tuple[ChatResult, UtteranceTurn | None]:
        """Handle ingress and create a visible-speech turn only after scheduling."""

        holder: list[UtteranceTurn] = []
        result = await self._handle_chat(
            envelope,
            planning_platform=platform,
            planning_holder=holder,
        )
        return result, holder[0] if holder else None

    async def activate_utterance(
        self,
        turn: UtteranceTurn | None,
        result: ChatResult,
    ) -> bool:
        if turn is None:
            return True
        return await self._utterances.activate(turn, result)

    async def wait_for_utterance_unit(
        self,
        turn: UtteranceTurn,
        result: ChatResult,
        *,
        unit_index: int,
    ) -> bool:
        return await self._utterances.wait_until_ready(
            turn,
            result,
            unit_index=unit_index,
        )

    async def mark_utterance_unit_started(
        self,
        turn: UtteranceTurn,
        result: ChatResult,
        *,
        unit_index: int,
    ) -> bool:
        return await self._utterances.mark_started(turn, result, unit_index=unit_index)

    async def cancel_utterance(
        self,
        turn: UtteranceTurn,
        result: ChatResult,
        *,
        reason_code: str,
    ) -> None:
        await self._utterances.cancel(turn, result, reason_code=reason_code)

    async def utterance_is_current(
        self,
        *,
        conversation_id: str,
        platform: str,
        session_id: str,
    ) -> bool:
        return await self._utterances.is_current(
            conversation_id=conversation_id,
            platform=platform,
            session_id=session_id,
        )

    async def utterance_session(self, session_id: str) -> StoredUtterance | None:
        return await self._utterances.stored_session(session_id)

    def utterance_delays_ms(self, result: ChatResult) -> list[int]:
        if result.utterance is None:
            return []
        return [self._utterances.delay_ms(unit) for unit in result.utterance.units]

    async def simulate_chat(self, envelope: IngressEnvelope) -> BehaviorSimulation:
        event = self._boundary.normalize(envelope)
        conversation_events = await self._conversation_events(event)
        momentum = ConversationMomentum.from_history(
            conversation_events,
            now=event.created_at,
        )
        preliminary_turn = self._social.decide_turn(event, momentum)
        state = (
            await self._social_state.get(event.conversation_id)
            if event.conversation_id is not None
            else None
        )
        pending_event_ids = [
            *(state.pending_event_ids if state is not None else []),
            event.event_id,
        ]
        schedule = self._schedule(
            event,
            momentum,
            preliminary_turn,
            pending_event_ids=pending_event_ids,
            cooldown_until=state.cooldown_until if state is not None else None,
        )
        turn = self._reply_necessity.apply(preliminary_turn, schedule)
        confirmation = None
        cancellation = None
        status_command = None
        proposal = None
        agent_goal = None
        if turn.mode != "observe":
            try:
                if self._agent_conversation is not None:
                    agent_goal = self._agent_conversation.preview_goal(event)
                if agent_goal is None:
                    confirmation = self._executive.confirmation(event)
                    cancellation = self._executive.cancellation(event)
                    status_command = self._executive.status(event)
                    if confirmation is None and cancellation is None and status_command is None:
                        proposal = self._executive.propose(event)
                        if proposal is None and self._agent_conversation is not None:
                            agent_goal = self._agent_conversation.preview_goal(event, fallback=True)
            except PermissionError:
                agent_goal = None
        if agent_goal is not None:
            turn = turn.model_copy(update={
                "mode": "act", "reason_code": "agent_goal",
                "expected_units_min": 1, "expected_units_max": 3,
            })
        preview_impression = (
            await self._social_state.latest_impression(event.conversation_id, now=event.created_at)
            if event.conversation_id is not None
            else None
        )
        context = self._context_compiler.compile(
            event,
            root_policy=self._root_policy,
            current_task=(
                {"goal": agent_goal, "status": "preview", "tools_selected_at_runtime": True}
                if agent_goal is not None
                else proposal.task.model_dump(mode="json") if proposal is not None else None
            ),
            available_capabilities=(
                proposal.task.allowed_capabilities if proposal is not None else []
            ),
            conversation_history=self._conversation_history(conversation_events[-8:]),
            interaction_plan=turn.model_dump(mode="json"),
            session_impression=(
                preview_impression.model_dump(mode="json")
                if preview_impression is not None
                else None
            ),
        )
        task_steps = []
        if proposal is not None:
            task_steps = [
                SimulatedTaskStep(
                    title=step.title,
                    handler=step.action.handler,
                    capability=step.action.capability_request.capability,
                    operation=step.action.capability_request.operation,
                    requires_confirmation=(
                        step.action.handler == "task_report"
                        or is_work_write_handler(step.action.handler)
                    ),
                )
                for step in proposal.plan.steps
            ]
        return BehaviorSimulation(
            event=event,
            turn=turn,
            momentum=momentum,
            schedule=schedule,
            context_sections=[section.kind.value for section in context.sections],
            task_goal=agent_goal or (proposal.task.goal if proposal is not None else None),
            task_steps=task_steps,
            would_call_model=(
                turn.mode != "observe"
                and confirmation is None
                and cancellation is None
                and status_command is None
                and (
                    proposal is None
                    or any(
                        step.action.handler
                        in {
                            "workspace_read",
                            "workspace_list",
                            "workspace_search",
                            "web_fetch",
                            "web_search",
                            "daily_plan_read",
                        }
                        for step in proposal.plan.steps
                    )
                )
            ),
            would_execute_tools=agent_goal is not None or proposal is not None,
        )

    async def handle_chat(
        self,
        envelope: IngressEnvelope,
        *,
        planning_turn: UtteranceTurn | None = None,
    ) -> ChatResult:
        return await self._handle_chat(envelope, planning_turn=planning_turn)

    async def _handle_chat(
        self,
        envelope: IngressEnvelope,
        *,
        planning_turn: UtteranceTurn | None = None,
        planning_platform: str | None = None,
        planning_holder: list[UtteranceTurn] | None = None,
    ) -> ChatResult:
        event = self._boundary.normalize(envelope)
        await self._events.add(event)
        await self._users.observe(envelope, event)
        await self._audit.append(
            action="event.ingested",
            actor_id=event.source_identity,
            conversation_id=event.conversation_id,
            outcome="accepted",
            details={
                "event_id": event.event_id,
                "source_type": event.source_type.value,
                "trust_level": event.trust_level.value,
                "authority_level": event.authority_level.value,
                "taint_labels": event.taint_labels,
            },
        )
        await self._observe_memory(event)
        if TaintLabel.SUSPECTED_INSTRUCTION.value in event.taint_labels:
            await self._audit.append(
                action="injection.detected",
                actor_id=event.source_identity,
                conversation_id=event.conversation_id,
                outcome="contained",
                details={"event_id": event.event_id, "taint_labels": event.taint_labels},
            )
        await self._event_bus.publish(event)

        conversation_events = await self._conversation_events(event)
        momentum = ConversationMomentum.from_history(
            conversation_events,
            now=event.created_at,
        )
        async with self._social_schedule_lock:
            preliminary_turn = self._social.decide_turn(event, momentum)
            social_state = await self._social_state.observe(event)
            schedule = self._schedule(
                event,
                momentum,
                preliminary_turn,
                pending_event_ids=(
                    social_state.pending_event_ids if social_state is not None else [event.event_id]
                ),
                cooldown_until=(social_state.cooldown_until if social_state is not None else None),
            )
            turn = self._reply_necessity.apply(preliminary_turn, schedule)
            if turn.mode != "observe" and planning_turn is None and planning_platform is not None:
                is_auto_group_turn = (
                    event.source_type is SourceType.GROUP_MESSAGE
                    and turn.reason_code == "group_auto_participation"
                )
                planning_turn = await self.begin_utterance_turn(
                    event.conversation_id,
                    platform=planning_platform,
                    replace_active=not is_auto_group_turn,
                )
                if planning_turn is None:
                    schedule = schedule.model_copy(
                        update={
                            "action": "suppress",
                            "score": 0.1,
                            "reasons": ["utterance_in_flight"],
                        }
                    )
                    turn = self._reply_necessity.apply(preliminary_turn, schedule)
                elif planning_holder is not None:
                    planning_holder.append(planning_turn)
            if social_state is not None and event.conversation_id is not None:
                await self._social_state.resolve(
                    event.conversation_id,
                    schedule,
                    now=event.created_at,
                    idle_exit_cycles=self._social_focus_idle_exit_cycles,
                )
        await self._audit.append(
            action="turn.scheduled",
            actor_id="living-agent",
            conversation_id=event.conversation_id,
            outcome=schedule.action,
            details={
                "event_id": event.event_id,
                "score": schedule.score,
                "reasons": schedule.reasons,
                "pending_event_ids": schedule.pending_event_ids,
                "delay_seconds": schedule.delay_seconds,
            },
        )
        await self._audit.append(
            action="turn.decided",
            actor_id="living-agent",
            conversation_id=event.conversation_id,
            outcome=turn.mode,
            details={"event_id": event.event_id, "reason_code": turn.reason_code},
        )
        await self._psyche.appraise(event, turn)
        psyche_state = await self._psyche.state()
        if turn.mode == "observe":
            return ChatResult(
                event=event,
                turn=turn,
                schedule=schedule,
                message=None,
                messages=[],
            )

        history = self._conversation_history(conversation_events[-8:])
        psyche = psyche_state.model_dump(mode="json")
        agent_result = await self._handle_agent(
            event, turn, schedule, history=history, psyche=psyche, planning_turn=planning_turn,
        )
        if agent_result is not None:
            return agent_result

        task_result = await self._task_conversation.handle(event)
        if task_result is not None:
            task_run = task_result.run
            if task_result.error == "denied":
                message = self._social.render_task_confirmation_denied()
            elif task_result.error == "missing":
                message = self._social.render_task_confirmation_missing()
            elif task_run is not None:
                message = await self._outcomes.task(
                    task_run, event, turn, history=history, psyche=psyche,
                    synthesize=task_result.synthesize,
                )
            else:
                raise RuntimeError("task conversation returned no outcome")
            return await self._visible_result(
                event, turn, schedule, message, planning_turn=planning_turn,
            )

        agent_result = await self._handle_agent(
            event, turn, schedule, history=history, psyche=psyche,
            planning_turn=planning_turn, fallback=True,
        )
        if agent_result is not None:
            return agent_result

        conversation_history = self._conversation_history(conversation_events[-8:])
        impression = None
        attention_cue = None
        if event.conversation_id is not None:
            impression_events = self._impression_events(
                [*conversation_events, event]
            )
            impression = await self._impressions.consider(
                event.conversation_id,
                impression_events,
                now=event.created_at,
            )
            attention_cue = await self._attention.consider(
                event,
                impression,
                conversation_events,
            )
        recalled_memories = []
        memory_trace_id: str | None = None
        recall_query = self._event_text(event).strip()
        if recall_query and TaintLabel.SUSPECTED_INSTRUCTION.value not in event.taint_labels:
            recall_batch = await self._memories.recall_with_trace(
                actor_id=event.source_identity or "anonymous",
                conversation_id=event.conversation_id,
                event_id=event.event_id,
                query=recall_query,
                limit=4,
                source_event_ids=[event.event_id],
                taint_labels=event.taint_labels,
            )
            recalled_memories = recall_batch.memories
            memory_trace_id = recall_batch.trace_id
        recalled_facts = [
            memory
            for memory in recalled_memories
            if memory.memory_layer is MemoryLayer.FACT
        ]
        recalled_narratives = [
            memory
            for memory in recalled_memories
            if memory.memory_layer is not MemoryLayer.FACT
        ]
        context = self._context_compiler.compile(
            event,
            root_policy=self._root_policy,
            conversation_history=conversation_history,
            retrieved_facts=[
                self._memories.fact_card(memory) for memory in recalled_facts
            ],
            retrieved_memories=[
                memory.model_dump(mode="json") for memory in recalled_narratives
            ],
            interaction_plan={
                "mode": turn.mode,
                "expected_units_min": turn.expected_units_min,
                "expected_units_max": turn.expected_units_max,
                "target_chars_per_unit": 36,
                "format": "newline_separated_plain_messages",
                "momentum": momentum.model_dump(),
            },
            psyche_state={
                "valence": psyche_state.valence,
                "arousal": psyche_state.arousal,
                "current_focus": psyche_state.current_focus,
                "focus_salience": psyche_state.focus_salience,
                "current_activity_id": psyche_state.current_activity_id,
            },
            session_impression=(
                impression.model_dump(mode="json") if impression is not None else None
            ),
            attention_cue=(
                attention_cue.model_dump(mode="json") if attention_cue is not None else None
            ),
        )
        if memory_trace_id is not None:
            await self._memories.mark_trace_injected(
                memory_trace_id,
                memory_ids=[memory.id for memory in recalled_memories],
                context_fingerprint=hashlib.sha256(
                    context.rendered.encode("utf-8")
                ).hexdigest(),
            )
        try:
            model_response = await self._models.generate(context, event)
        except LLMProviderError as exc:
            await self._audit.append(
                action="model.reply_suppressed",
                actor_id="living-agent",
                conversation_id=event.conversation_id,
                outcome="ignored",
                details={
                    "event_id": event.event_id,
                    "provider": exc.provider,
                    "model": exc.model,
                    "error_code": exc.code,
                    "attempts": exc.attempts,
                    "reason_code": "model_failure",
                },
            )
            if memory_trace_id is not None:
                await self._memories.mark_response_supported(
                    memory_trace_id,
                    response_text="",
                    corroborating_text=self._corroborating_text(
                        event=event,
                        conversation_history=conversation_history,
                        impression=impression,
                        attention_cue=attention_cue,
                    ),
                )
            return ChatResult(
                event=event,
                turn=turn,
                schedule=schedule,
                message=None,
                messages=[],
                utterance=None,
                memory_trace_id=memory_trace_id,
            )
        if planning_turn is not None and not await self._utterances.turn_is_current(planning_turn):
            if memory_trace_id is not None:
                await self._memories.mark_response_supported(
                    memory_trace_id,
                    response_text="",
                    corroborating_text=self._corroborating_text(
                        event=event,
                        conversation_history=conversation_history,
                        impression=impression,
                        attention_cue=attention_cue,
                    ),
                )
            await self._audit.append(
                action="model.result_discarded",
                actor_id="living-agent",
                conversation_id=event.conversation_id,
                outcome="stale",
                details={
                    "event_id": event.event_id,
                    "generation": planning_turn.generation,
                    "reason_code": "superseded_during_planning",
                },
            )
            return ChatResult(
                event=event,
                turn=turn,
                schedule=schedule,
                message=None,
                messages=[],
                memory_trace_id=memory_trace_id,
            )
        claim_evidence = model_response.claim_evidence.model_copy(
            update={
                "memory_ids": sorted(
                    set(model_response.claim_evidence.memory_ids)
                    | {memory.id for memory in recalled_memories}
                )
            }
        )
        approved = await self._models.approve(model_response.text, claim_evidence, event)
        utterance_text = (
            model_response.text if approved else self._social.render_continuity_block()
        )
        if memory_trace_id is not None:
            await self._memories.mark_response_supported(
                memory_trace_id,
                response_text=utterance_text,
                corroborating_text=self._corroborating_text(
                    event=event,
                    conversation_history=conversation_history,
                    impression=impression,
                    attention_cue=attention_cue,
                ),
            )
        utterance = self._social.plan_utterance(utterance_text, turn)
        if not approved:
            utterance.units[0].function = "continuity_block"
        messages = [unit.text for unit in utterance.units]
        await self._audit.append(
            action="response.generated",
            actor_id="living-agent",
            conversation_id=event.conversation_id,
            outcome="success",
            details={
                "event_id": event.event_id,
                "provider": model_response.provider,
                "context_sections": [section.kind.value for section in context.sections],
            },
        )
        return ChatResult(
            event=event,
            turn=turn,
            schedule=schedule,
            message=messages[0],
            messages=messages,
            utterance=utterance,
            recalled_memory_ids=(
                [memory.id for memory in recalled_memories]
                if approved
                else []
            ),
            memory_trace_id=memory_trace_id,
            attention_cue_id=(
                attention_cue.cue_id
                if attention_cue is not None and approved
                else None
            ),
        )

    async def record_delivery(
        self, result: ChatResult, *, unit_index: int, platform: str,
    ) -> TrustedEvent:
        return await self._delivery.record_delivery(
            result, unit_index=unit_index, platform=platform,
        )

    async def record_persisted_utterance_delivery(
        self, *, session_id: str, platform: str, conversation_id: str,
        unit_index: int, recovered_after_restart: bool,
    ) -> DeliveryResult:
        return await self._delivery.record_persisted_utterance_delivery(
            session_id=session_id, platform=platform, conversation_id=conversation_id,
            unit_index=unit_index, recovered_after_restart=recovered_after_restart,
        )

    async def _observe_memory(self, event: TrustedEvent) -> None:
        try:
            await self._memories.observe(event)
        except Exception as exc:
            await self._audit_memory_side_effect_failure(
                event,
                operation="observe",
                error=exc,
            )

    async def _audit_memory_side_effect_failure(
        self,
        event: TrustedEvent,
        *,
        operation: str,
        error: Exception,
    ) -> None:
        await self._audit.append(
            action="memory.side_effect",
            actor_id="living-agent",
            conversation_id=event.conversation_id,
            outcome="failure",
            details={
                "event_id": event.event_id,
                "operation": operation,
                "error_code": type(error).__name__,
            },
        )

    async def _conversation_events(self, event: TrustedEvent) -> list[TrustedEvent]:
        if event.conversation_id is None:
            return []
        return await self._events.recent_for_conversation(
            event.conversation_id,
            limit=128,
            exclude_event_id=event.event_id,
        )

    def _schedule(
        self,
        event: TrustedEvent,
        momentum: ConversationMomentum,
        turn: TurnDecision,
        *,
        pending_event_ids: list[str],
        cooldown_until: datetime | None,
    ) -> TurnScheduleDecision:
        if not self._social_scheduler_enabled:
            return TurnScheduleDecision(
                action="trigger" if turn.mode != "observe" else "suppress",
                score=turn.urgency,
                reasons=["scheduler_disabled"],
                pending_event_ids=pending_event_ids,
            )
        return self._reply_necessity.evaluate(
            event,
            momentum,
            turn,
            pending_event_ids=pending_event_ids,
            cooldown_until=cooldown_until,
        )

    @staticmethod
    def _conversation_history(history: list[TrustedEvent]) -> list[dict[str, Any]]:
        return [
            {
                "event_id": item.event_id,
                "role": "assistant" if item.source_type is SourceType.AGENT_MESSAGE else "user",
                "content": item.content,
                "created_at": item.created_at.isoformat(),
                "taint_labels": sorted(item.taint_labels),
            }
            for item in history
        ]

    @classmethod
    def _impression_events(
        cls,
        events: list[TrustedEvent],
    ) -> list[TrustedEvent]:
        """Keep structured facts out of the lossy Session Impression channel."""

        filtered: list[TrustedEvent] = []
        seen: set[str] = set()
        for event in events:
            if event.event_id in seen:
                continue
            seen.add(event.event_id)
            text = cls._event_text(event).strip()
            routed = route_recall(text)
            if extract_fact(text) is not None or routed.route in {
                RecallRoute.EXACT_FACT,
                RecallRoute.FACT_SET,
            }:
                continue
            filtered.append(event)
        return filtered

    @staticmethod
    def _corroborating_text(
        *,
        event: TrustedEvent,
        conversation_history: list[dict[str, Any]],
        impression: Any,
        attention_cue: Any,
    ) -> str:
        """Serialize only non-memory context that could independently contain a fact."""

        payload = {
            "request": event.content,
            "recent_conversation": conversation_history,
            "session_impression": (
                impression.model_dump(mode="json") if impression is not None else None
            ),
            "attention_cue": (
                attention_cue.model_dump(mode="json") if attention_cue is not None else None
            ),
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)

    @staticmethod
    def _event_text(event: TrustedEvent) -> str:
        if isinstance(event.content, str):
            return event.content
        text = event.content.get("text", "")
        return text if isinstance(text, str) else ""
