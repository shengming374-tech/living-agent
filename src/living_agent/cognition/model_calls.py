"""One model-call audit and evidence gate for chat and tool-result replies."""

from __future__ import annotations

from living_agent.audit.service import AuditService
from living_agent.cognition.context_compiler import CompiledContext
from living_agent.evaluation.continuity_critic import ContinuityCritic, CriticAction
from living_agent.models.claims import ClaimEvidence
from living_agent.models.events import TrustedEvent
from living_agent.providers.llm import LLMProvider, LLMProviderError, ModelResponse


class ModelCalls:
    def __init__(
        self, *, llm: LLMProvider, audit: AuditService, critic: ContinuityCritic,
    ) -> None:
        self._llm = llm
        self._audit = audit
        self._critic = critic

    async def generate(
        self, context: CompiledContext, event: TrustedEvent, *, phase: str | None = None,
    ) -> ModelResponse:
        phase_details = {"phase": phase} if phase is not None else {}
        try:
            response = await self._llm.generate(context)
        except LLMProviderError as exc:
            await self._audit.append(
                action="model.called", actor_id="living-agent",
                conversation_id=event.conversation_id, outcome="failure",
                details={
                    "event_id": event.event_id, "provider": exc.provider,
                    "model": exc.model, "error_code": exc.code, "attempts": exc.attempts,
                    **phase_details,
                },
            )
            raise
        await self._audit.append(
            action="model.called", actor_id="living-agent",
            conversation_id=event.conversation_id, outcome="success",
            details={
                "event_id": event.event_id, "provider": response.provider,
                "model": response.model, "attempts": response.attempts,
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
                "image_count": sum(len(section.images) for section in context.sections),
                "vision_model": response.vision_model, "vision_mode": response.vision_mode,
                "vision_cache_hits": response.vision_cache_hits,
                "vision_prompt_tokens": response.vision_usage.prompt_tokens,
                "vision_completion_tokens": response.vision_usage.completion_tokens,
                **phase_details,
            },
        )
        return response

    async def approve(
        self, text: str, evidence: ClaimEvidence, event: TrustedEvent,
        *, phase: str | None = None,
    ) -> bool:
        decision = await self._critic.evaluate(
            text, evidence, conversation_id=event.conversation_id,
            actor_id=event.source_identity or "anonymous",
        )
        if decision.action is CriticAction.APPROVE:
            return True
        await self._audit.append(
            action="continuity.blocked", actor_id="living-agent",
            conversation_id=event.conversation_id, outcome="blocked",
            details={
                "event_id": event.event_id, "reason_codes": decision.reason_codes,
                **({"phase": phase} if phase is not None else {}),
            },
        )
        return False
