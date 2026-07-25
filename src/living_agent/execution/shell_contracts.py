"""Typed contracts for confirmed, workspace-scoped process execution."""

from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator

SHELL_EXECUTE_CAPABILITY = "shell.command.execute"
SHELL_EXECUTE_HANDLER = "shell_execute"

_SHELL_OPERATOR_TOKENS = frozenset(
    {
        "|",
        "||",
        "&",
        "&&",
        ";",
        ">",
        ">>",
        "<",
        "<<",
        "2>",
        "2>>",
    }
)


class ShellExecuteArguments(BaseModel):
    """A process invocation without a command interpreter."""

    model_config = ConfigDict(extra="forbid")

    argv: list[str] = Field(min_length=1, max_length=64)
    cwd: str = Field(default=".", min_length=1, max_length=1000)
    timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    max_output_chars: int = Field(default=20_000, ge=1, le=100_000)

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for token in value:
            candidate = token.strip()
            if (
                not candidate
                or len(candidate) > 1000
                or "\x00" in candidate
                or "\n" in candidate
                or "\r" in candidate
                or candidate in _SHELL_OPERATOR_TOKENS
            ):
                raise ValueError("shell arguments must be bounded literal tokens")
            normalized.append(candidate)
        executable = normalized[0]
        if "/" in executable or "\\" in executable or executable in {".", ".."}:
            raise ValueError("shell executable must be an allowlisted command name")
        return normalized

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, value: str) -> str:
        normalized = value.strip().replace("\\", "/")
        path = PurePosixPath(normalized)
        if (
            not normalized
            or "\x00" in normalized
            or path.is_absolute()
            or ".." in path.parts
        ):
            raise ValueError("shell cwd must stay inside the configured workspace")
        return normalized


def shell_scope(arguments: ShellExecuteArguments) -> str:
    """Bind grants to the exact argv, cwd, and execution limits."""

    payload = json.dumps(
        arguments.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"shell/{digest}"


def shell_scope_matches(arguments: BaseModel, scope: str) -> bool:
    return isinstance(arguments, ShellExecuteArguments) and scope == shell_scope(arguments)
