"""Isolated stdlib-only plugin runner for one JSON-RPC request."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import os
import sys
from collections.abc import Awaitable
from pathlib import Path
from typing import Any

MAX_REQUEST_BYTES = 1_000_000


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--plugin-dir", required=True)
    parser.add_argument("--entrypoint", required=True)
    return parser.parse_args()


def _load_request() -> dict[str, Any]:
    raw = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
    if not raw or len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("invalid request size")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("request must be an object")
    if payload.get("jsonrpc") != "2.0" or payload.get("method") != "invoke":
        raise ValueError("unsupported RPC request")
    params = payload.get("params")
    if not isinstance(params, dict):
        raise ValueError("params must be an object")
    return payload


def _invoke(entrypoint: str, params: dict[str, Any]) -> dict[str, Any]:
    module = importlib.import_module(entrypoint)
    handler = getattr(module, "invoke", None)
    if not callable(handler):
        raise TypeError("plugin entrypoint must expose invoke(params)")
    result = handler(params)
    if inspect.isawaitable(result):
        result = asyncio.run(_resolve_awaitable(result))
    if not isinstance(result, dict):
        raise TypeError("plugin result must be an object")
    return result


async def _resolve_awaitable(value: Awaitable[Any]) -> Any:
    return await value


def main() -> int:
    args = _parse_args()
    plugin_root = Path(args.plugin_dir).resolve()
    os.chdir(plugin_root)
    sys.path.insert(0, str(plugin_root))
    request_id: object = None
    try:
        request = _load_request()
        request_id = request.get("id")
        params = request["params"]
        result = _invoke(args.entrypoint, params)
        response = {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception:
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": "plugin invocation failed"},
        }
    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
