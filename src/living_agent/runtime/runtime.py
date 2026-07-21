"""Phase 1 trusted-message vertical slice."""

from __future__ import annotations

import hashlib
from typing import Any

from living_agent.audit.service import AuditService
from living_agent.cognition.context_compiler import CompiledContext, ContextCompiler
from living_agent.cognition.executive import ExecutiveCognition
from living_agent.cognition.social import SocialCognition
from living_agent.evaluation.continuity_critic import ContinuityCritic, CriticAction
from living_agent.evaluation.simulator import BehaviorSimulation, SimulatedTaskStep
from living_agent.execution.repository import TaskNotFoundError, TaskStateError
from living_agent.execution.service import TaskConfirmationDeniedError, TaskService
from living_agent.interaction.momentum import ConversationMomentum
from living_agent.interaction.repository import (
    DeliveryDisposition,
    DeliveryResult,
    StoredUtterance,
)
from living_agent.interaction.utterance import UtteranceCoordinator, UtteranceTurn
from living_agent.memory.service import MemoryService
from living_agent.models.conversation import ChatResult
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
    ) -> UtteranceTurn | None:
        if conversation_id is None:
            return None
        return await self._utterances.begin_turn(conversation_id, platform=platform)

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
        turn = self._social.decide_turn(event, momentum)
        confirmation = None
        proposal = None
        if turn.mode != "observe":
            confirmation = self._executive.confirmation(event)
            proposal = self._executive.propose(event) if confirmation is None else None
        context = self._context_compiler.compile(
            event,
            root_policy=self._root_policy,
            current_task=(proposal.task.model_dump(mode="json") if proposal is not None else None),
            available_capabilities=(
                proposal.task.allowed_capabilities if proposal is not None else []
            ),
            conversation_history=self._conversation_history(conversation_events[-8:]),
            interaction_plan=turn.model_dump(mode="json"),
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
            context_sections=[section.kind.value for section in context.sections],
            task_goal=proposal.task.goal if proposal is not None else None,
            task_steps=task_steps,
            would_call_model=(
                turn.mode != "observe" and proposal is None and confirmation is None
            ),
            would_execute_tools=proposal is not None,
        )

    async def handle_chat(self, envelope: IngressEnvelope) -> ChatResult:
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
        turn = self._social.decide_turn(event, momentum)
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
            return ChatResult(event=event, turn=turn, message=None, messages=[])

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
                message=messages[0],
                messages=messages,
                utterance=utterance,
            )

        conversation_history = self._conversation_history(conversation_events[-8:])
        recalled_memories = []
        if TaintLabel.SUSPECTED_INSTRUCTION.value not in event.taint_labels:
            recalled_memories = await self._memories.recall(
                actor_id=event.source_identity or "anonymous",
                conversation_id=event.conversation_id,
                query=self._event_text(event),
                limit=4,
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
            failure_messages = [unit.text for unit in failure_utterance.units]
            return ChatResult(
                event=event,
                turn=turn,
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
            },
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
            message=messages[0],
            messages=messages,
            utterance=utterance,
            recalled_memory_ids=(
                [memory.id for memory in recalled_memories]
                if continuity.action is CriticAction.APPROVE
                else []
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
