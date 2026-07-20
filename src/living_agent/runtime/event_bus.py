"""Small async in-process event bus without global mutable state."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from living_agent.models.events import TrustedEvent

EventHandler = Callable[[TrustedEvent], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event: TrustedEvent) -> None:
        handlers = [*self._handlers.get(event.event_type, []), *self._handlers.get("*", [])]
        if handlers:
            await asyncio.gather(*(handler(event) for handler in handlers))
