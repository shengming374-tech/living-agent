"""Phase 1 trusted-message vertical slice."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime
from typing import Any

from living_agent.audit.service import AuditService
from living_agent.cognition.context_compiler import CompiledContext, ContextCompiler
from living_agent.cognition.executive import ExecutiveCognition
from living_agent.cognition.social import SocialCognition
from living_agent.evaluation.continuity_critic import ContinuityCritic, CriticAction
from living_agent.evaluation.simulator import BehaviorSimulation, SimulatedTaskStep
from living_agent.execution.repository import TaskNotFoundError, TaskStateError
from living_agent.execution.service import TaskConfirmationDeniedError, TaskService
from living_agent.interaction.impressions import AttentionCueService, SessionImpressionService
from living_agent.interaction.momentum import ConversationMomentum
from living_agent.interaction.repository import (
    DeliveryDisposition,
    DeliveryResult,
    StoredUtterance,
)
from living_agent.interaction.scheduler import ReplyNecessityEvaluator
from living_agent.interaction.social_state import SocialStateRepository
from living_agent.interaction.utterance import UtteranceCoordinator, UtteranceTurn
from living_agent.memory.service import MemoryService
from living_agent.models.conversation import ChatResult, TurnDecision, TurnScheduleDecision
from living_agent.models.events import IngressEnvelope, SourceType, TrustedEvent
from living_agent.providers.llm import LLMProvider, LLMProviderError
from living_agent.psyche.service import PsycheService
from living_agent.runtime.event_bus import EventBus
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
    ) -> None:
        self._boundary = boundary
        self._events = events
        self._audit = audit
        self._event_bus = event_bus
        self._social = social
        self._executive = executive
        self._tasks = tasks
        self._context_compiler = context_compiler
        self._llm = llm
        self._root_policy = root_policy
        self._psyche = psyche
        self._continuity_critic = continuity_critic
        self._memories = memories
        self._users = users
        self._utterances = utterances
        self._reply_necessity = reply_necessity
        self._social_state = social_state
        self._impressions = impressions
        self._attention = attention
        self._social_scheduler_enabled = social_scheduler_enabled
        self._social_focus_idle_exit_cycles = social_focus_idle_exit_cycles
        self._social_cooldown_seconds = social_cooldown_seconds
        self._social_schedule_lock = asyncio.Lock()

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
        proposal = None
        if turn.mode != "observe":
            confirmation = self._executive.confirmation(event)
            proposal = self._executive.propose(event) if confirmation is None else None
        preview_impression = (
            await self._social_state.latest_impression(event.conversation_id, now=event.created_at)
            if event.conversation_id is not None
            else None
        )
        context = self._context_compiler.compile(
            event,
            root_policy=self._root_policy,
            current_task=(proposal.task.model_dump(mode="json") if proposal is not None else None),
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
                    requires_confirmation=step.action.handler == "task_report",
                )
                for step in proposal.plan.steps
            ]
        return BehaviorSimulation(
            event=event,
            turn=turn,
            momentum=momentum,
            schedule=schedule,
            context_sections=[section.kind.value for section in context.sections],
            task_goal=proposal.task.goal if proposal is not None else None,
            task_steps=task_steps,
            would_call_model=(turn.mode != "observe" and proposal is None and confirmation is None),
            would_execute_tools=proposal is not None,
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
        await self._memories.observe(event)
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
                    social_state.pending_event_ids
                    if social_state is not None
                    else [event.event_id]
                ),
                cooldown_until=(
                    social_state.cooldown_until if social_state is not None else None
                ),
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

        confirmation = self._executive.confirmation(event)
        if confirmation is not None:
            try:
                task_run = await self._tasks.confirm(
                    task_id=confirmation.task_id,
                    conversation_id=event.conversation_id,
                    actor_id=event.source_identity or "anonymous",
                )
                message = self._social.render_task_run(task_run)
            except TaskConfirmationDeniedError:
                message = self._social.render_task_confirmation_denied()
            except (TaskNotFoundError, TaskStateError):
                message = self._social.render_task_confirmation_missing()
            utterance = self._social.plan_utterance(message, turn)
            messages = [unit.text for unit in utterance.units]
            return ChatResult(
                event=event,
                turn=turn,
                schedule=schedule,
                message=messages[0],
                messages=messages,
                utterance=utterance,
            )

        proposal = self._executive.propose(event)
        if proposal is not None:
            task_run = await self._tasks.submit(proposal)
            message = self._social.render_task_run(task_run)
            utterance = self._social.plan_utterance(message, turn)
            messages = [unit.text for unit in utterance.units]
            return ChatResult(
                event=event,
                turn=turn,
                schedule=schedule,
                message=messages[0],
                messages=messages,
                utterance=utterance,
            )

        conversation_history = self._conversation_history(conversation_events[-8:])
        impression = None
        attention_cue = None
        if event.conversation_id is not None:
            impression = await self._impressions.consider(
                event.conversation_id,
                [*conversation_events, event],
                now=event.created_at,
            )
            attention_cue = await self._attention.consider(
                event,
                impression,
                conversation_events,
            )
        recalled_memories = []
        recall_query = self._event_text(event).strip()
        if recall_query and TaintLabel.SUSPECTED_INSTRUCTION.value not in event.taint_labels:
            recalled_memories = await self._memories.recall(
                actor_id=event.source_identity or "anonymous",
                conversation_id=event.conversation_id,
                query=recall_query,
                limit=4,
                source_event_ids=[event.event_id],
                taint_labels=event.taint_labels,
            )
        context = self._context_compiler.compile(
            event,
            root_policy=self._root_policy,
            conversation_history=conversation_history,
            retrieved_memories=[memory.model_dump(mode="json") for memory in recalled_memories],
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
        try:
            model_response = await self._llm.generate(context)
        except LLMProviderError as exc:
            await self._audit.append(
                action="model.called",
                actor_id="living-agent",
                conversation_id=event.conversation_id,
                outcome="failure",
                details={
                    "event_id": event.event_id,
                    "provider": exc.provider,
                    "model": exc.model,
                    "error_code": exc.code,
                },
            )
            failure_message = self._social.render_model_failure()
            failure_utterance = self._social.plan_utterance(failure_message, turn)
            failure_utterance.units[0].function = "model_failure"
            failure_messages = [unit.text for unit in failure_utterance.units]
            return ChatResult(
                event=event,
                turn=turn,
                schedule=schedule,
                message=failure_messages[0],
                messages=failure_messages,
                utterance=failure_utterance,
            )
        await self._audit.append(
            action="model.called",
            actor_id="living-agent",
            conversation_id=event.conversation_id,
            outcome="success",
            details={
                "event_id": event.event_id,
                "provider": model_response.provider,
                "model": model_response.model,
                "prompt_tokens": model_response.usage.prompt_tokens,
                "completion_tokens": model_response.usage.completion_tokens,
                "total_tokens": model_response.usage.total_tokens,
                "image_count": sum(len(section.images) for section in context.sections),
                "vision_model": model_response.vision_model,
                "vision_mode": model_response.vision_mode,
                "vision_cache_hits": model_response.vision_cache_hits,
                "vision_prompt_tokens": model_response.vision_usage.prompt_tokens,
                "vision_completion_tokens": model_response.vision_usage.completion_tokens,
            },
        )
        if planning_turn is not None and not await self._utterances.turn_is_current(planning_turn):
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
            )
        claim_evidence = model_response.claim_evidence.model_copy(
            update={
                "memory_ids": sorted(
                    set(model_response.claim_evidence.memory_ids)
                    | {memory.id for memory in recalled_memories}
                )
            }
        )
        continuity = await self._continuity_critic.evaluate(
            model_response.text,
            claim_evidence,
            conversation_id=event.conversation_id,
            actor_id=event.source_identity or "anonymous",
        )
        if continuity.action is CriticAction.APPROVE:
            message = self._social.render_model_text(model_response.text)
        else:
            message = self._social.render_continuity_block()
            await self._audit.append(
                action="continuity.blocked",
                actor_id="living-agent",
                conversation_id=event.conversation_id,
                outcome="blocked",
                details={
                    "event_id": event.event_id,
                    "reason_codes": continuity.reason_codes,
                },
            )
        utterance_text = (
            model_response.text if continuity.action is CriticAction.APPROVE else message
        )
        utterance = self._social.plan_utterance(utterance_text, turn)
        if continuity.action is not CriticAction.APPROVE:
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
                if continuity.action is CriticAction.APPROVE
                else []
            ),
            attention_cue_id=(
                attention_cue.cue_id
                if attention_cue is not None and continuity.action is CriticAction.APPROVE
                else None
            ),
        )

    async def record_delivery(
        self,
        result: ChatResult,
        *,
        unit_index: int,
        platform: str,
    ) -> TrustedEvent:
        conversation_id = result.event.conversation_id
        messages = result.messages or ([result.message] if result.message is not None else [])
        if conversation_id is None or not messages:
            raise ValueError("delivered replies require a conversation and visible message")
        if unit_index < 0 or unit_index >= len(messages):
            raise ValueError("delivered reply unit index is outside the generated utterance")
        session_id = result.utterance.session_id if result.utterance is not None else None
        if result.utterance is None:
            delivered = await self._events.add_agent_message(
                conversation_id=conversation_id,
                content=messages[unit_index],
                source_event_id=result.event.event_id,
                utterance_session_id=None,
                unit_index=unit_index,
                delivery_platform=platform,
            )
        else:
            assert session_id is not None
            delivery = await self._utterances.record_delivery(
                conversation_id=conversation_id,
                platform=platform,
                session_id=session_id,
                unit_index=unit_index,
            )
            self._require_recorded_delivery(delivery)
            if delivery.event is None:
                raise RuntimeError("persistent utterance delivery did not create an event")
            delivered = delivery.event
        if unit_index == 0:
            response_id = session_id or result.event.event_id
            for memory_id in result.recalled_memory_ids:
                await self._memories.record_usage(
                    memory_id,
                    response_id=response_id,
                    conversation_id=conversation_id,
                )
            await self._memories.consider_self_candidate(delivered)
            if result.attention_cue_id is not None:
                await self._social_state.mark_cue_used(result.attention_cue_id)
            await self._social_state.mark_agent_spoke(
                conversation_id,
                now=delivered.created_at,
                cooldown_seconds=self._social_cooldown_seconds,
            )
        await self._audit.append(
            action="response.delivered",
            actor_id="living-agent",
            conversation_id=conversation_id,
            outcome="success",
            details={
                "event_id": result.event.event_id,
                "utterance_session_id": session_id,
                "unit_index": unit_index,
                "platform": platform,
            },
        )
        return delivered

    async def record_persisted_utterance_delivery(
        self,
        *,
        session_id: str,
        platform: str,
        conversation_id: str,
        unit_index: int,
        recovered_after_restart: bool,
    ) -> DeliveryResult:
        """Record a transport receipt for a Session recovered after restart."""

        stored = await self._utterances.stored_session(session_id)
        if stored is None:
            return DeliveryResult(DeliveryDisposition.SESSION_NOT_FOUND, None)
        delivery = await self._utterances.record_delivery(
            conversation_id=conversation_id,
            platform=platform,
            session_id=session_id,
            unit_index=unit_index,
        )
        if delivery.disposition is not DeliveryDisposition.RECORDED:
            return delivery
        if delivery.event is None or delivery.utterance is None:
            raise RuntimeError("persistent utterance delivery returned incomplete evidence")
        if unit_index == 0:
            for memory_id in stored.recalled_memory_ids:
                await self._memories.record_usage(
                    memory_id,
                    response_id=session_id,
                    conversation_id=conversation_id,
                )
            await self._memories.consider_self_candidate(delivery.event)
            if stored.attention_cue_id is not None:
                await self._social_state.mark_cue_used(stored.attention_cue_id)
            await self._social_state.mark_agent_spoke(
                conversation_id,
                now=delivery.event.created_at,
                cooldown_seconds=self._social_cooldown_seconds,
            )
        await self._audit.append(
            action="response.delivered",
            actor_id="living-agent",
            conversation_id=conversation_id,
            outcome="success",
            details={
                "event_id": stored.source_event_id,
                "utterance_session_id": session_id,
                "unit_index": unit_index,
                "platform": platform,
                "recovered_after_restart": recovered_after_restart,
            },
        )
        return delivery

    @staticmethod
    def _require_recorded_delivery(delivery: DeliveryResult) -> None:
        if delivery.disposition is DeliveryDisposition.RECORDED:
            return
        reasons = {
            DeliveryDisposition.ALREADY_RECORDED: "delivered reply was already recorded",
            DeliveryDisposition.OUT_OF_ORDER: "delivered reply units must be recorded in order",
            DeliveryDisposition.INTERRUPTED: "utterance session was interrupted",
            DeliveryDisposition.SCOPE_MISMATCH: "utterance session scope mismatch",
            DeliveryDisposition.SESSION_NOT_FOUND: "utterance session was not found",
            DeliveryDisposition.UNIT_NOT_ISSUED: "delivered reply unit was not issued",
        }
        raise ValueError(reasons[delivery.disposition])

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

    @staticmethod
    def _event_text(event: TrustedEvent) -> str:
        if isinstance(event.content, str):
            return event.content
        text = event.content.get("text", "")
        return text if isinstance(text, str) else ""
