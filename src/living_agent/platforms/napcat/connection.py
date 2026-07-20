"""Concurrent OneBot action/response multiplexing over one reverse WebSocket."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

FrameHandler = Callable[[dict[str, Any], "NapCatConnection"], Coroutine[Any, Any, None]]
FrameIssueHandler = Callable[[str], Awaitable[None]]


class NapCatConnectionError(RuntimeError):
    pass


class NapCatActionTimeoutError(NapCatConnectionError):
    pass


class NapCatConnection:
    def __init__(
        self,
        websocket: WebSocket,
        *,
        action_timeout_seconds: float,
        max_frame_bytes: int,
        max_in_flight_events: int,
    ) -> None:
        self._websocket = websocket
        self._action_timeout_seconds = action_timeout_seconds
        self._max_frame_bytes = max_frame_bytes
        self._max_in_flight_events = max_in_flight_events
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._send_lock = asyncio.Lock()
        self._closed = False

    async def run(
        self,
        handler: FrameHandler,
        issue_handler: FrameIssueHandler,
    ) -> None:
        try:
            while True:
                frame = await self._receive_frame(issue_handler)
                if frame is None:
                    continue
                echo = frame.get("echo")
                if isinstance(echo, str) and echo in self._pending:
                    future = self._pending[echo]
                    if not future.done():
                        future.set_result(frame)
                    continue
                if "echo" in frame and "status" in frame:
                    await issue_handler("unmatched_action_response")
                    continue
                if len(self._tasks) >= self._max_in_flight_events:
                    await issue_handler("too_many_in_flight_events")
                    continue
                task: asyncio.Task[None] = asyncio.create_task(handler(frame, self))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        except WebSocketDisconnect:
            pass
        finally:
            self._closed = True
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(NapCatConnectionError("NapCat disconnected"))
            if self._tasks:
                drain = asyncio.create_task(self._drain_tasks())
                try:
                    await asyncio.shield(drain)
                except asyncio.CancelledError:
                    await drain
                    raise

    async def call_action(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._closed:
            raise NapCatConnectionError("NapCat connection is closed")
        echo = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending[echo] = future
        try:
            async with self._send_lock:
                try:
                    await self._websocket.send_json(
                        {"action": action, "params": params, "echo": echo}
                    )
                except Exception as exc:
                    raise NapCatConnectionError("could not send NapCat action") from exc
            try:
                return await asyncio.wait_for(
                    future,
                    timeout=self._action_timeout_seconds,
                )
            except TimeoutError as exc:
                raise NapCatActionTimeoutError("NapCat action timed out") from exc
        finally:
            self._pending.pop(echo, None)

    async def _receive_frame(
        self,
        issue_handler: FrameIssueHandler,
    ) -> dict[str, Any] | None:
        message = await self._websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(code=message.get("code", 1000))
        raw: str | bytes | None = message.get("text")
        if raw is None:
            raw = message.get("bytes")
        if raw is None:
            await issue_handler("unsupported_websocket_frame")
            return None
        size = len(raw.encode("utf-8")) if isinstance(raw, str) else len(raw)
        if size > self._max_frame_bytes:
            await issue_handler("frame_too_large")
            return None
        try:
            decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            value = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError):
            await issue_handler("invalid_json")
            return None
        if not isinstance(value, dict):
            await issue_handler("frame_not_object")
            return None
        return value

    async def _drain_tasks(self) -> None:
        await asyncio.gather(*self._tasks, return_exceptions=True)
