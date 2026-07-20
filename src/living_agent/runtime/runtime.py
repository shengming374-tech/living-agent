"""Phase 1 trusted-message vertical slice."""

from __future__ import annotations

import hashlib
from typing import Any

from living_agent.audit.service import AuditService
from living_agent.cognition.context_compiler import CompiledContext, ContextCompiler
from living_agent.cognition.executive import ExecutiveCognition
from living_agent.cognition.social import SocialCognition
from living_agent.evaluation.continuity_critic import ContinuityCritic, CriticAction
from living_agent.execution.executor import CalculatorTaskExecutor
from living_agent.interaction.momentum import ConversationMomentum
from living_agent.models.conversation import ChatResult
from living_agent.models.events import IngressEnvelope, SourceType, TrustedEvent
from living_agent.providers.llm import LLMProvider, LLMProviderError
from living_agent.psyche.service import PsycheService
from living_agent.runtime.event_bus import EventBus
from living_agent.storage.events import EventRepository
from living_agent.trust.boundary import TrustBoundary
from living_agent.trust.taint import TaintLabel


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
        task_executor: CalculatorTaskExecutor,
        context_compiler: ContextCompiler,
        llm: LLMProvider,
        root_policy: str,
        psyche: PsycheService,
        continuity_critic: ContinuityCritic,
    ) -> None:
        self._boundary = boundary
        self._events = events
        self._audit = audit
        self._event_bus = event_bus
        self._social = social
        self._executive = executive
        self._task_executor = task_executor
        self._context_compiler = context_compiler
        self._llm = llm
        self._root_policy = root_policy
        self._psyche = psyche
        self._continuity_critic = continuity_critic

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

    async def handle_chat(self, envelope: IngressEnvelope) -> ChatResult:
        event = self._boundary.normalize(envelope)
        await self._events.add(event)
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

        proposal = self._executive.propose(event)
        if proposal is not None:
            activity = await self._psyche.start_activity(
                kind="calculator_task",
                summary=f"Executing verified task {proposal.task.task_id}.",
                source_event_ids=[event.event_id],
            )
            try:
                task_result = await self._task_executor.execute(proposal)
            except Exception:
                await self._psyche.finish_activity(
                    activity.activity_id,
                    success=False,
                    evidence_ids=[],
                )
                raise
            await self._psyche.finish_activity(
                activity.activity_id,
                success=task_result.success,
                evidence_ids=[proposal.task.task_id] if task_result.success else [],
            )
            message = self._social.render_task_result(task_result)
            utterance = self._social.plan_utterance(message, turn)
            messages = [unit.text for unit in utterance.units]
            await self._audit.append(
                action="task.completed",
                actor_id="living-agent",
                conversation_id=event.conversation_id,
                outcome="success" if task_result.success else "failure",
                details={
                    "event_id": event.event_id,
                    "task_id": proposal.task.task_id,
                    "evidence_count": len(task_result.evidence),
                    "errors": task_result.errors,
                },
            )
            return ChatResult(
                event=event,
                turn=turn,
                message=messages[0],
                messages=messages,
                utterance=utterance,
            )

        conversation_history = self._conversation_history(conversation_events)
        context = self._context_compiler.compile(
            event,
            root_policy=self._root_policy,
            conversation_history=conversation_history,
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
            return ChatResult(
                event=event,
                turn=turn,
                message=self._social.render_model_failure(),
                messages=[self._social.render_model_failure()],
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
        continuity = await self._continuity_critic.evaluate(
            model_response.text,
            model_response.claim_evidence,
            conversation_id=event.conversation_id,
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
        delivered = await self._events.add_agent_message(
            conversation_id=conversation_id,
            content=messages[unit_index],
            source_event_id=result.event.event_id,
            utterance_session_id=session_id,
            unit_index=unit_index,
            delivery_platform=platform,
        )
        if result.utterance is not None:
            result.utterance.sent_count = max(result.utterance.sent_count, unit_index + 1)
            result.utterance.state = (
                "completed"
                if result.utterance.sent_count >= len(result.utterance.units)
                else "sending"
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

    async def _conversation_events(self, event: TrustedEvent) -> list[TrustedEvent]:
        if event.conversation_id is None:
            return []
        return await self._events.recent_for_conversation(
            event.conversation_id,
            limit=8,
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
