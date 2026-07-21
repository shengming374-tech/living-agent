from __future__ import annotations

import socket
import subprocess
from pathlib import Path
from typing import Any


def invoke(params: dict[str, Any]) -> dict[str, Any]:
    arguments = params.get("arguments", {})
    read_path = Path(str(arguments.get("read_path", "")))
    write_path = Path(str(arguments.get("write_path", "")))
    return {
        "read_succeeded": _attempt(lambda: read_path.read_text(encoding="utf-8")),
        "write_succeeded": _attempt(lambda: write_path.write_text("blocked", encoding="utf-8")),
        "network_succeeded": _attempt(_open_network),
        "process_succeeded": _attempt(
            lambda: subprocess.run(
                ["/usr/bin/true"],
                check=True,
                capture_output=True,
                timeout=0.5,
            )
        ),
    }


def _open_network() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))


def _attempt(operation: Any) -> bool:
    try:
        operation()
    except (OSError, subprocess.SubprocessError):
        return False
    return True
