"""Runtime-owned lifecycle for interruptible, paced visible speech."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from living_agent.audit.service import AuditService
from living_agent.interaction.repository import (
    DeliveryDisposition,
    DeliveryResult,
    StoredUtterance,
    UtteranceRepository,
)
from living_agent.models.conversation import ChatResult, SpeechUnit, UtteranceSession


@dataclass(frozen=True, slots=True)
class UtteranceTurn:
    conversation_id: str
    platform: str
    generation: int
    replaced_session_id: str | None = None


@dataclass(slots=True)
class _ActiveUtterance:
    session: UtteranceSession
    source_event_id: str
    recalled_memory_ids: tuple[str, ...]
    attention_cue_id: str | None
    cancelled: asyncio.Event
    started_count: int = 0


class UtteranceCoordinator:
    """Discard stale plans and pace only the currently active utterance."""

    def __init__(
        self,
        *,
        audit: AuditService,
        delays_enabled: bool,
        repository: UtteranceRepository | None = None,
    ) -> None:
        self._audit = audit
        self._delays_enabled = delays_enabled
        self._repository = repository
        self._lock = asyncio.Lock()
        self._generations: dict[tuple[str, str], int] = {}
        self._planning: dict[tuple[str, str], int] = {}
        self._active: dict[tuple[str, str], _ActiveUtterance] = {}

    async def initialize(self) -> None:
        """Restore the newest in-flight Session per scope without resending it."""

        if self._repository is None:
            return
        async with self._lock:
            watermarks = await self._repository.generation_watermarks()
            recoverable = await self._repository.list_recoverable()
            for key, generation in watermarks.items():
                self._generations[key] = max(self._generations.get(key, 0), generation)

            selected: dict[tuple[str, str], StoredUtterance] = {}
            for stored in recoverable:
                key = (stored.platform, stored.conversation_id)
                current = selected.get(key)
                if current is None or (
                    stored.generation,
                    stored.updated_at,
                ) > (current.generation, current.updated_at):
                    selected[key] = stored

            stale = [
                stored
                for stored in recoverable
                if selected[(stored.platform, stored.conversation_id)] != stored
            ]
            for stored in selected.values():
                key = (stored.platform, stored.conversation_id)
                self._active[key] = _ActiveUtterance(
                    session=stored.session,
                    source_event_id=stored.source_event_id,
                    recalled_memory_ids=stored.recalled_memory_ids,
                    attention_cue_id=stored.attention_cue_id,
                    cancelled=asyncio.Event(),
                    started_count=stored.started_count,
                )

        for stored in stale:
            await self._repository.mark_cancelled(
                stored.session.session_id,
                reason="superseded_during_recovery",
            )
            stored.session.state = "cancelled"
            await self._audit_interruption(
                _ActiveUtterance(
                    session=stored.session,
                    source_event_id=stored.source_event_id,
                    recalled_memory_ids=stored.recalled_memory_ids,
                    attention_cue_id=stored.attention_cue_id,
                    cancelled=asyncio.Event(),
                    started_count=stored.started_count,
                ),
                conversation_id=stored.conversation_id,
                platform=stored.platform,
                reason_code="superseded_during_recovery",
            )
        for stored in selected.values():
            await self._audit.append(
                action="utterance.recovered",
                actor_id="living-agent",
                conversation_id=stored.conversation_id,
                outcome="recovered",
                details={
                    "utterance_session_id": stored.session.session_id,
                    "platform": stored.platform,
                    "source_event_id": stored.source_event_id,
                    "generation": stored.generation,
                    "sent_count": stored.session.sent_count,
                    "unit_count": len(stored.session.units),
                    "automatic_resend": False,
                },
            )

    async def begin_turn(
        self,
        conversation_id: str,
        *,
        platform: str,
        replace_active: bool = True,
    ) -> UtteranceTurn | None:
        key = (platform, conversation_id)
        interrupted: _ActiveUtterance | None = None
        async with self._lock:
            if not replace_active and (key in self._planning or key in self._active):
                return None
            generation = self._generations.get(key, 0) + 1
            self._generations[key] = generation
            self._planning[key] = generation
            interrupted = self._active.get(key)
            if interrupted is not None:
                if self._repository is not None:
                    await self._repository.mark_cancelled(
                        interrupted.session.session_id,
                        reason="new_inbound_message",
                    )
                self._active.pop(key, None)
                interrupted.session.state = "cancelled"
                interrupted.cancelled.set()
        if interrupted is not None:
            await self._audit_interruption(
                interrupted,
                conversation_id=conversation_id,
                platform=platform,
                reason_code="new_inbound_message",
            )
        return UtteranceTurn(
            conversation_id=conversation_id,
            platform=platform,
            generation=generation,
            replaced_session_id=(
                interrupted.session.session_id if interrupted is not None else None
            ),
        )

    async def activate(self, turn: UtteranceTurn, result: ChatResult) -> bool:
        session = result.utterance
        if session is None or not result.messages:
            async with self._lock:
                if self._planning.get((turn.platform, turn.conversation_id)) == turn.generation:
                    self._planning.pop((turn.platform, turn.conversation_id), None)
            return True
        key = (turn.platform, turn.conversation_id)
        stale = False
        async with self._lock:
            if self._generations.get(key) != turn.generation:
                session.state = "cancelled"
                stale = True
            else:
                self._planning.pop(key, None)
                session.state = "planned"
                if self._repository is not None:
                    await self._repository.create(
                        session,
                        platform=turn.platform,
                        conversation_id=turn.conversation_id,
                        source_event_id=result.event.event_id,
                        recalled_memory_ids=result.recalled_memory_ids,
                        attention_cue_id=result.attention_cue_id,
                        generation=turn.generation,
                        replaced_session_id=turn.replaced_session_id,
                    )
                self._active[key] = _ActiveUtterance(
                    session=session,
                    source_event_id=result.event.event_id,
                    recalled_memory_ids=tuple(result.recalled_memory_ids),
                    attention_cue_id=result.attention_cue_id,
                    cancelled=asyncio.Event(),
                )
        if stale:
            result.message = None
            result.messages = []
            await self._audit.append(
                action="utterance.interrupted",
                actor_id="living-agent",
                conversation_id=turn.conversation_id,
                outcome="cancelled",
                details={
                    "event_id": result.event.event_id,
                    "utterance_session_id": session.session_id,
                    "platform": turn.platform,
                    "sent_count": 0,
                    "delivered_count": 0,
                    "unsent_count": len(session.units),
                    "reason_code": "superseded_before_delivery",
                },
            )
            return False
        await self._audit.append(
            action="utterance.planned",
            actor_id="living-agent",
            conversation_id=turn.conversation_id,
            outcome="planned",
            details={
                "event_id": result.event.event_id,
                "utterance_session_id": session.session_id,
                "platform": turn.platform,
                "unit_count": len(session.units),
            },
        )
        if turn.replaced_session_id is not None:
            await self._audit.append(
                action="utterance.replanned",
                actor_id="living-agent",
                conversation_id=turn.conversation_id,
                outcome="replanned",
                details={
                    "replaced_session_id": turn.replaced_session_id,
                    "utterance_session_id": session.session_id,
                    "event_id": result.event.event_id,
                    "platform": turn.platform,
                },
            )
        return True

    async def wait_until_ready(
        self,
        turn: UtteranceTurn,
        result: ChatResult,
        *,
        unit_index: int,
    ) -> bool:
        active = await self._current(turn, result)
        if active is None or unit_index != active.started_count:
            return False
        session = result.utterance
        if session is None:
            return False
        delay_ms = self.delay_ms(session.units[unit_index])
        if delay_ms:
            try:
                await asyncio.wait_for(active.cancelled.wait(), timeout=delay_ms / 1000)
                return False
            except TimeoutError:
                pass
        return await self._current(turn, result) is active

    async def mark_started(
        self,
        turn: UtteranceTurn,
        result: ChatResult,
        *,
        unit_index: int,
    ) -> bool:
        key = (turn.platform, turn.conversation_id)
        async with self._lock:
            active = self._active.get(key)
            if (
                active is None
                or result.utterance is None
                or active.session.session_id != result.utterance.session_id
                or self._generations.get(key) != turn.generation
                or unit_index != active.started_count
            ):
                return False
            if self._repository is not None:
                stored = await self._repository.mark_started(
                    active.session.session_id,
                    unit_index=unit_index,
                )
                if stored is None:
                    return False
            active.started_count += 1
            active.session.state = "sending"
            return True

    async def is_current(
        self,
        *,
        conversation_id: str,
        platform: str,
        session_id: str,
    ) -> bool:
        async with self._lock:
            active = self._active.get((platform, conversation_id))
            return active is not None and active.session.session_id == session_id

    async def turn_is_current(self, turn: UtteranceTurn) -> bool:
        """Check planning generation before a late model result changes visible state."""

        async with self._lock:
            return self._generations.get((turn.platform, turn.conversation_id)) == turn.generation

    async def stored_session(self, session_id: str) -> StoredUtterance | None:
        if self._repository is None:
            return None
        return await self._repository.get(session_id)

    async def record_delivery(
        self,
        *,
        conversation_id: str,
        platform: str,
        session_id: str,
        unit_index: int,
    ) -> DeliveryResult:
        key = (platform, conversation_id)
        async with self._lock:
            active = self._active.get(key)
            if self._repository is None:
                if active is None or active.session.session_id != session_id:
                    return DeliveryResult(DeliveryDisposition.INTERRUPTED, None)
                active.session.sent_count = max(active.session.sent_count, unit_index + 1)
                active.session.state = (
                    "completed"
                    if active.session.sent_count >= len(active.session.units)
                    else "sending"
                )
                if active.session.state == "completed":
                    self._active.pop(key, None)
                return DeliveryResult(DeliveryDisposition.RECORDED, None)

            stored = await self._repository.get(session_id)
            if stored is None:
                return DeliveryResult(DeliveryDisposition.SESSION_NOT_FOUND, None)
            if stored.platform != platform or stored.conversation_id != conversation_id:
                return DeliveryResult(DeliveryDisposition.SCOPE_MISMATCH, stored)
            if unit_index < stored.session.sent_count:
                return DeliveryResult(DeliveryDisposition.ALREADY_RECORDED, stored)
            started_before_cancellation = (
                stored.session.state == "cancelled" and unit_index < stored.started_count
            )
            if (
                active is None or active.session.session_id != session_id
            ) and not started_before_cancellation:
                return DeliveryResult(DeliveryDisposition.INTERRUPTED, stored)
            delivery = await self._repository.record_delivery(
                session_id,
                platform=platform,
                conversation_id=conversation_id,
                unit_index=unit_index,
            )
            if delivery.utterance is not None and active is not None:
                updated = delivery.utterance
                active.session.sent_count = updated.session.sent_count
                active.session.state = updated.session.state
                active.started_count = updated.started_count
            if (
                delivery.disposition is DeliveryDisposition.RECORDED
                and active is not None
                and active.session.state == "completed"
            ):
                self._active.pop(key, None)
            return delivery

    async def cancel(
        self,
        turn: UtteranceTurn,
        result: ChatResult,
        *,
        reason_code: str,
    ) -> None:
        key = (turn.platform, turn.conversation_id)
        interrupted: _ActiveUtterance | None = None
        async with self._lock:
            if self._planning.get(key) == turn.generation:
                self._planning.pop(key, None)
            active = self._active.get(key)
            if (
                active is not None
                and result.utterance is not None
                and active.session.session_id == result.utterance.session_id
            ):
                if self._repository is not None:
                    await self._repository.mark_cancelled(
                        active.session.session_id,
                        reason=reason_code,
                    )
                interrupted = self._active.pop(key)
                interrupted.session.state = "cancelled"
                interrupted.cancelled.set()
        if interrupted is not None:
            await self._audit_interruption(
                interrupted,
                conversation_id=turn.conversation_id,
                platform=turn.platform,
                reason_code=reason_code,
            )

    def delay_ms(self, unit: SpeechUnit) -> int:
        if not self._delays_enabled:
            return 0
        return (unit.delay_min_ms + unit.delay_max_ms) // 2

    async def _current(
        self,
        turn: UtteranceTurn,
        result: ChatResult,
    ) -> _ActiveUtterance | None:
        if result.utterance is None:
            return None
        key = (turn.platform, turn.conversation_id)
        async with self._lock:
            active = self._active.get(key)
            if (
                active is None
                or active.session.session_id != result.utterance.session_id
                or self._generations.get(key) != turn.generation
            ):
                return None
            return active

    async def _audit_interruption(
        self,
        active: _ActiveUtterance,
        *,
        conversation_id: str,
        platform: str,
        reason_code: str,
    ) -> None:
        sent_count = max(active.started_count, active.session.sent_count)
        await self._audit.append(
            action="utterance.interrupted",
            actor_id="living-agent",
            conversation_id=conversation_id,
            outcome="cancelled",
            details={
                "event_id": active.source_event_id,
                "utterance_session_id": active.session.session_id,
                "platform": platform,
                "sent_count": sent_count,
                "delivered_count": active.session.sent_count,
                "unsent_count": max(0, len(active.session.units) - sent_count),
                "reason_code": reason_code,
            },
        )
