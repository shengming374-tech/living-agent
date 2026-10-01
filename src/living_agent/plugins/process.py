"""Host-side subprocess lifecycle and JSON-RPC validation."""

from __future__ import annotations

import asyncio
import os
import signal
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
from living_agent.plugins.sandbox import PluginSandbox, PluginSandboxMode


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


class PluginOutputLimitError(PluginProtocolError):
    error_code = "plugin_output_limit"


class PluginProcess:
    def __init__(
        self,
        *,
        timeout_seconds: float = 2.0,
        max_output_bytes: int = 1_000_000,
        sandbox_mode: PluginSandboxMode = "auto",
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("plugin timeout must be positive")
        self._timeout_seconds = timeout_seconds
        self._max_output_bytes = max_output_bytes
        self._worker_path = Path(__file__).with_name("worker.py").resolve()
        self._sandbox = PluginSandbox(mode=sandbox_mode)

    @property
    def sandbox_backend(self) -> str | None:
        return self._sandbox.status.backend

    @property
    def sandbox_enforced(self) -> bool:
        return self._sandbox.status.enforced

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
            "PYTHONDONTWRITEBYTECODE": "1",
            "LIVING_AGENT_PLUGIN_ID": record.manifest.id,
        }
        command = self._sandbox.command(
            worker_path=self._worker_path,
            plugin_root=record.root,
            entrypoint=record.manifest.entrypoint,
        )
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
            start_new_session=True,
        )
        payload = request.model_dump_json().encode("utf-8") + b"\n"
        if process.stdin is None or process.stdout is None or process.stderr is None:
            await self._terminate(process)
            raise PluginProtocolError("plugin process pipes were not created")

        process.stdin.write(payload)
        await process.stdin.drain()
        process.stdin.close()
        await process.stdin.wait_closed()
        total_output = [0]

        async def read_pipe(stream: asyncio.StreamReader, *, capture: bool) -> bytes:
            chunks: list[bytes] = []
            while chunk := await stream.read(64 * 1024):
                total_output[0] += len(chunk)
                if total_output[0] > self._max_output_bytes:
                    raise PluginOutputLimitError("plugin output exceeded the host size limit")
                if capture:
                    chunks.append(chunk)
            return b"".join(chunks)

        stdout_task = asyncio.create_task(read_pipe(process.stdout, capture=True))
        stderr_task = asyncio.create_task(read_pipe(process.stderr, capture=False))
        wait_task = asyncio.create_task(process.wait())
        try:
            stdout, _stderr, _returncode = await asyncio.wait_for(
                asyncio.gather(stdout_task, stderr_task, wait_task),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as exc:
            await self._terminate(process)
            raise PluginTimeoutError("plugin call exceeded its host timeout") from exc
        except asyncio.CancelledError:
            await self._terminate(process)
            raise
        except PluginOutputLimitError:
            await self._terminate(process)
            raise
        finally:
            for task in (stdout_task, stderr_task, wait_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(stdout_task, stderr_task, wait_task, return_exceptions=True)

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
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=0.25)
            return
        except TimeoutError:
            pass
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        await process.wait()
