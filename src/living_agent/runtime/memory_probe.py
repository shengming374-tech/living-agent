"""Owner-only memory experiments isolated from chat side effects."""

from __future__ import annotations

import hashlib

from living_agent.audit.service import AuditService
from living_agent.cognition.context_compiler import ContextCompiler
from living_agent.memory.service import MemoryService
from living_agent.models.events import IngressEnvelope, SourceType
from living_agent.models.memory import MemoryProbeRequest, MemoryProbeResponse, MemoryProbeVariant
from living_agent.providers.llm import LLMProvider
from living_agent.trust.boundary import TrustBoundary


class MemoryProbeRunner:
    def __init__(
        self, *, boundary: TrustBoundary, compiler: ContextCompiler, llm: LLMProvider,
        memories: MemoryService, audit: AuditService, root_policy: str,
    ) -> None:
        self._boundary = boundary
        self._context_compiler = compiler
        self._llm = llm
        self._memories = memories
        self._audit = audit
        self._root_policy = root_policy

    async def run(
        self,
        request: MemoryProbeRequest,
        *,
        actor_id: str,
    ) -> MemoryProbeResponse:
        """Run an owner-only, two-call isolation check without chat side effects."""

        facts = await self._memories.exact_facts(
            entity_id=request.subject_id,
            fact_keys=request.fact_keys,
            owner=True,
        )
        trace = await self._memories.start_probe_trace(
            entity_id=request.subject_id,
            prompt=request.prompt,
            facts=facts,
        )
        probe_event = self._boundary.normalize(
            IngressEnvelope(
                content=request.prompt,
                source_type=SourceType.DIRECT_MESSAGE,
                source_identity=actor_id,
                conversation_id=trace.trace.conversation_id,
                authenticated=True,
            )
        )
        with_context = self._context_compiler.compile(
            probe_event,
            root_policy=self._root_policy,
            retrieved_facts=[self._memories.fact_card(fact) for fact in facts],
        )
        without_context = self._context_compiler.compile(
            probe_event,
            root_policy=self._root_policy,
        )
        await self._memories.mark_trace_injected(
            trace.trace.trace_id,
            memory_ids=[fact.id for fact in facts],
            context_fingerprint=hashlib.sha256(
                with_context.rendered.encode("utf-8")
            ).hexdigest(),
        )
        with_response = await self._llm.generate(with_context)
        without_response = await self._llm.generate(without_context)
        completed = await self._memories.mark_response_supported(
            trace.trace.trace_id,
            response_text=with_response.text,
            corroborating_text=without_response.text,
        )
        matches = [item for item in completed.items if item.response_match is True]
        if not matches:
            verdict = "not_used"
        elif any(item.source_overlap for item in matches):
            verdict = "inconclusive"
        else:
            verdict = "supported"
        await self._audit.append(
            action="memory.probe.ran",
            actor_id=actor_id,
            conversation_id=trace.trace.conversation_id,
            outcome=verdict,
            details={
                "trace_id": trace.trace.trace_id,
                "subject_id": request.subject_id,
                "fact_keys": request.fact_keys,
                "memory_ids": [fact.id for fact in facts],
                "model_call_count": 2,
            },
        )
        return MemoryProbeResponse(
            verdict=verdict,
            support_mode=completed.trace.support_mode,
            with_memory=MemoryProbeVariant(
                text=with_response.text,
                selected_memory_ids=[fact.id for fact in facts],
            ),
            without_memory=MemoryProbeVariant(
                text=without_response.text,
                selected_memory_ids=[],
            ),
            trace_id=trace.trace.trace_id,
        )
