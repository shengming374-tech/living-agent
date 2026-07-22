"""Restart-safe nightly scheduler for Phase 8 sleep cycles."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from living_agent.audit.service import AuditService
from living_agent.life.service import LifeService


class LifeScheduler:
    def __init__(
        self,
        *,
        service: LifeService,
        audit: AuditService,
        enabled: bool,
        nightly_hour: int,
        poll_seconds: float,
    ) -> None:
        self._service = service
        self._audit = audit
        self._enabled = enabled
        self._nightly_hour = nightly_hour
        self._poll_seconds = poll_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if not self._enabled or self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="living-agent-life-scheduler")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        self._stop.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_due(self, *, now: datetime | None = None) -> bool:
        current = (now or datetime.now(UTC)).astimezone(self._service.timezone)
        if current.hour < self._nightly_hour:
            return False
        cycle_date = (current - timedelta(days=1)).date()
        cycles = await self._service.sleep_cycles(limit=370)
        if any(cycle.cycle_date == cycle_date for cycle in cycles):
            return False
        await self._service.run_sleep_cycle(
            cycle_date,
            actor_id="living-agent-scheduler",
            trigger="scheduler",
        )
        return True

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_due()
            except Exception as exc:
                await self._audit.append(
                    action="life.scheduler_failed",
                    actor_id="living-agent-scheduler",
                    outcome="failed",
                    details={"error_code": type(exc).__name__},
                )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                continue
