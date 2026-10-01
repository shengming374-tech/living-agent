"""Isolated per-user application data / 各系统独立的用户应用数据。"""

from __future__ import annotations

import json
import os
import secrets
import sys
import tempfile
from pathlib import Path
from typing import IO, Any

from pydantic import BaseModel, ConfigDict, Field


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actor_id: str = Field(min_length=1, max_length=255)
    token: str = Field(min_length=32, max_length=4096, repr=False)


def default_profile() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "LivingAgent"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/LivingAgent"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "living-agent"


def private_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomic owner-only metadata; tokens never appear in URLs / 原子写入私有元数据。"""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix=".living-agent-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def initialize_profile(root: Path) -> Credentials:
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    (root / "workspace").mkdir(exist_ok=True)
    path = root / "credentials.json"
    if path.exists():
        # Invalid saved credentials fail closed / 损坏的凭据不能自动重置。
        return Credentials.model_validate_json(path.read_text(encoding="utf-8"))
    credentials = Credentials(
        actor_id=os.environ.get("LIVING_AGENT_OWNER_ID", "owner-local"),
        token=os.environ.get("LIVING_AGENT_MANAGEMENT_API_TOKEN") or secrets.token_urlsafe(48),
    )
    private_json(path, credentials.model_dump())
    return credentials


class ProfileLock:
    """One worker per profile on macOS/Linux/Windows / 每个数据目录只允许一个运行时。"""

    def __init__(self, root: Path) -> None:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._file: IO[bytes] = (root / "runtime.lock").open("a+b")

    def __enter__(self) -> ProfileLock:
        try:
            if sys.platform == "win32":
                import msvcrt

                self._file.seek(0)
                self._file.write(b"0")
                self._file.flush()
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._file.close()
            raise RuntimeError("该数据目录已有运行时 / This profile is already running") from exc
        return self

    def __exit__(self, *args: object) -> None:
        self._file.close()
