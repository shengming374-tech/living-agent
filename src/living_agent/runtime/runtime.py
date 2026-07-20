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
from living_agent.models.conversation import ChatResult
from living_agent.models.events import IngressEnvelope
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

        turn = self._social.decide_turn(event)
        await self._audit.append(
            action="turn.decided",
            actor_id="living-agent",
            conversation_id=event.conversation_id,
            outcome=turn.mode,
            details={"event_id": event.event_id, "reason_code": turn.reason_code},
        )
        await self._psyche.appraise(event, turn)
        if turn.mode == "observe":
            return ChatResult(event=event, turn=turn, message=None)

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
            return ChatResult(event=event, turn=turn, message=message)

        context = self._context_compiler.compile(event, root_policy=self._root_policy)
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
        return ChatResult(event=event, turn=turn, message=message)
