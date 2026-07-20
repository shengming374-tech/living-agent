"""Host-side subprocess lifecycle and JSON-RPC validation."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from living_agent.plugins.registry import PluginRecord
from living_agent.plugins.rpc import (
    PluginCallParams,
    PluginInvocationResult,
    RpcRequest,
    RpcResponse,
)


class PluginProcessError(RuntimeError):
    error_code = "plugin_process_error"


class PluginTimeoutError(PluginProcessError):
    error_code = "plugin_timeout"


class PluginCrashedError(PluginProcessError):
    error_code = "plugin_crashed"


class PluginProtocolError(PluginProcessError):
    error_code = "plugin_protocol_error"


class PluginInvocationError(PluginProcessError):
    error_code = "plugin_invocation_error"


class PluginProcess:
    def __init__(self, *, timeout_seconds: float = 2.0, max_output_bytes: int = 1_000_000) -> None:
        if timeout_seconds <= 0:
            raise ValueError("plugin timeout must be positive")
        self._timeout_seconds = timeout_seconds
        self._max_output_bytes = max_output_bytes
        self._worker_path = Path(__file__).with_name("worker.py").resolve()

    async def invoke(
        self,
        record: PluginRecord,
        *,
        operation: str,
        arguments: dict[str, Any],
    ) -> PluginInvocationResult:
        request = RpcRequest(
            id=str(uuid4()),
            params=PluginCallParams(operation=operation, arguments=arguments),
        )
        environment = {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "LIVING_AGENT_PLUGIN_ID": record.manifest.id,
        }
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            str(self._worker_path),
            "--plugin-dir",
            str(record.root),
            "--entrypoint",
            record.manifest.entrypoint,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
            start_new_session=True,
        )
        payload = request.model_dump_json().encode("utf-8") + b"\n"
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(payload),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            await self._terminate(process)
            raise PluginTimeoutError("plugin call exceeded its host timeout") from exc
        except asyncio.CancelledError:
            await self._terminate(process)
            raise

        if process.returncode != 0:
            raise PluginCrashedError("plugin process exited unexpectedly")
        if len(stdout) > self._max_output_bytes:
            raise PluginProtocolError("plugin response exceeded the host size limit")
        try:
            response = RpcResponse.model_validate_json(stdout)
        except ValidationError as exc:
            raise PluginProtocolError("plugin returned an invalid RPC response") from exc
        if response.id != request.id:
            raise PluginProtocolError("plugin response id did not match the request")
        if response.error is not None:
            raise PluginInvocationError(response.error.message)
        if response.result is None:
            raise PluginProtocolError("plugin returned no result")
        return PluginInvocationResult(
            plugin_id=record.manifest.id,
            operation=operation,
            output=response.result,
        )

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=0.25)
            return
        except TimeoutError:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        await process.wait()
