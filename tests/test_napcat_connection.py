from __future__ import annotations

import asyncio
from typing import Any, cast

from fastapi import WebSocket

from living_agent.platforms.napcat.connection import NapCatConnection


class FakeWebSocket:
    def __init__(self) -> None:
        self.inbound: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.action_sent = asyncio.Event()

    async def receive(self) -> dict[str, Any]:
        return await self.inbound.get()

    async def send_json(self, payload: dict[str, Any]) -> None:
        self.sent.append(payload)
        self.action_sent.set()


def connection(
    websocket: FakeWebSocket,
    *,
    workers: int,
    queued: int,
) -> NapCatConnection:
    return NapCatConnection(
        cast(WebSocket, websocket),
        action_timeout_seconds=0.5,
        max_frame_bytes=4096,
        max_in_flight_events=workers,
        max_queued_events=queued,
    )


async def disconnect(websocket: FakeWebSocket) -> None:
    await websocket.inbound.put({"type": "websocket.disconnect", "code": 1000})


async def test_fifo_absorbs_more_events_than_worker_concurrency() -> None:
    websocket = FakeWebSocket()
    active = 0
    max_active = 0
    started: list[int] = []
    completed: list[int] = []
    all_completed = asyncio.Event()
    issues: list[str] = []

    async def handler(
        frame: dict[str, Any],
        _connection: NapCatConnection,
    ) -> None:
        nonlocal active, max_active
        started.append(frame["sequence"])
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        completed.append(frame["sequence"])
        if len(completed) == 24:
            all_completed.set()

    async def issue(reason: str) -> None:
        issues.append(reason)

    run = asyncio.create_task(connection(websocket, workers=16, queued=256).run(handler, issue))
    for sequence in range(24):
        await websocket.inbound.put(
            {"type": "websocket.receive", "text": f'{{"sequence":{sequence}}}'}
        )
    await asyncio.wait_for(all_completed.wait(), timeout=1.0)
    await disconnect(websocket)
    await run

    assert started == list(range(24))
    assert sorted(completed) == list(range(24))
    assert max_active == 16
    assert issues == []


async def test_action_response_is_correlated_while_event_queue_is_saturated() -> None:
    websocket = FakeWebSocket()
    action_result: dict[str, Any] | None = None
    second_processed = asyncio.Event()
    issues: list[str] = []

    async def handler(
        frame: dict[str, Any],
        active: NapCatConnection,
    ) -> None:
        nonlocal action_result
        if frame["sequence"] == 1:
            action_result = await active.call_action("send_private_msg", {"message": "safe"})
        else:
            second_processed.set()

    async def issue(reason: str) -> None:
        issues.append(reason)

    run = asyncio.create_task(connection(websocket, workers=1, queued=1).run(handler, issue))
    await websocket.inbound.put(
        {"type": "websocket.receive", "text": '{"sequence":1}'}
    )
    await asyncio.wait_for(websocket.action_sent.wait(), timeout=0.5)
    await websocket.inbound.put(
        {"type": "websocket.receive", "text": '{"sequence":2}'}
    )
    echo = websocket.sent[0]["echo"]
    await websocket.inbound.put(
        {
            "type": "websocket.receive",
            "text": f'{{"status":"ok","retcode":0,"echo":"{echo}"}}',
        }
    )
    await asyncio.wait_for(second_processed.wait(), timeout=0.5)
    await disconnect(websocket)
    await run

    assert action_result == {"status": "ok", "retcode": 0, "echo": echo}
    assert issues == []


async def test_full_queue_and_disconnect_cleanup_are_auditable() -> None:
    websocket = FakeWebSocket()
    release = asyncio.Event()
    first_started = asyncio.Event()
    issues: list[str] = []

    async def handler(
        frame: dict[str, Any],
        _connection: NapCatConnection,
    ) -> None:
        if frame["sequence"] == 1:
            first_started.set()
            await release.wait()

    async def issue(reason: str) -> None:
        issues.append(reason)

    run = asyncio.create_task(connection(websocket, workers=1, queued=1).run(handler, issue))
    await websocket.inbound.put(
        {"type": "websocket.receive", "text": '{"sequence":1}'}
    )
    await asyncio.wait_for(first_started.wait(), timeout=0.5)
    await websocket.inbound.put(
        {"type": "websocket.receive", "text": '{"sequence":2}'}
    )
    await websocket.inbound.put(
        {"type": "websocket.receive", "text": '{"sequence":3}'}
    )
    await disconnect(websocket)
    release.set()
    await run

    assert "event_queue_full" in issues
    assert "events_discarded_on_disconnect" in issues
