"""Persist transport receipts and apply effects only to delivered speech."""

from __future__ import annotations

from living_agent.audit.service import AuditService
from living_agent.interaction.repository import DeliveryDisposition, DeliveryResult
from living_agent.interaction.social_state import SocialStateRepository
from living_agent.interaction.utterance import UtteranceCoordinator
from living_agent.memory.service import MemoryService
from living_agent.models.conversation import ChatResult
from living_agent.models.events import TrustedEvent
from living_agent.storage.events import EventRepository


class DeliveryRecorder:
    def __init__(
        self, *, events: EventRepository, audit: AuditService, memories: MemoryService,
        utterances: UtteranceCoordinator, social_state: SocialStateRepository,
        cooldown_seconds: float,
    ) -> None:
        self._events = events
        self._audit = audit
        self._memories = memories
        self._utterances = utterances
        self._social_state = social_state
        self._social_cooldown_seconds = cooldown_seconds

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
            await self._after_first_delivery(
                delivered, memory_trace_id=result.memory_trace_id,
                attention_cue_id=result.attention_cue_id,
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
            await self._after_first_delivery(
                delivery.event, memory_trace_id=stored.memory_trace_id,
                attention_cue_id=stored.attention_cue_id,
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

    async def _after_first_delivery(
        self, event: TrustedEvent, *, memory_trace_id: str | None,
        attention_cue_id: str | None,
    ) -> None:
        assert event.conversation_id is not None
        if memory_trace_id is not None:
            await self._memories.mark_trace_delivered(memory_trace_id, response_id=event.event_id)
        await self._consider_self_memory(event)
        if attention_cue_id is not None:
            await self._social_state.mark_cue_used(attention_cue_id)
        await self._social_state.mark_agent_spoke(
            event.conversation_id, now=event.created_at,
            cooldown_seconds=self._social_cooldown_seconds,
        )

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

    async def _consider_self_memory(self, event: TrustedEvent) -> None:
        try:
            await self._memories.consider_self_candidate(event)
        except Exception as exc:
            await self._audit.append(
                action="memory.side_effect", actor_id="living-agent",
                conversation_id=event.conversation_id, outcome="failure",
                details={"event_id": event.event_id, "operation": "consider_self_candidate",
                         "error_code": type(exc).__name__},
            )
