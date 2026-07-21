"""Runtime-owned lifecycle for interruptible, paced visible speech."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from living_agent.audit.service import AuditService
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
    cancelled: asyncio.Event
    started_count: int = 0


class UtteranceCoordinator:
    """Discard stale plans and pace only the currently active utterance."""

    def __init__(
        self,
        *,
        audit: AuditService,
        delays_enabled: bool,
    ) -> None:
        self._audit = audit
        self._delays_enabled = delays_enabled
        self._lock = asyncio.Lock()
        self._generations: dict[tuple[str, str], int] = {}
        self._active: dict[tuple[str, str], _ActiveUtterance] = {}

    async def begin_turn(self, conversation_id: str, *, platform: str) -> UtteranceTurn:
        key = (platform, conversation_id)
        interrupted: _ActiveUtterance | None = None
        async with self._lock:
            generation = self._generations.get(key, 0) + 1
            self._generations[key] = generation
            interrupted = self._active.pop(key, None)
            if interrupted is not None:
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
            return True
        key = (turn.platform, turn.conversation_id)
        stale = False
        async with self._lock:
            if self._generations.get(key) != turn.generation:
                session.state = "cancelled"
                stale = True
            else:
                session.state = "planned"
                self._active[key] = _ActiveUtterance(
                    session=session,
                    source_event_id=result.event.event_id,
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

    async def record_delivery(
        self,
        *,
        conversation_id: str,
        platform: str,
        session: UtteranceSession,
    ) -> None:
        key = (platform, conversation_id)
        async with self._lock:
            active = self._active.get(key)
            if active is None or active.session.session_id != session.session_id:
                return
            if session.state == "completed":
                self._active.pop(key, None)

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
            active = self._active.get(key)
            if (
                active is not None
                and result.utterance is not None
                and active.session.session_id == result.utterance.session_id
            ):
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
