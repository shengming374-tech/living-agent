"""Platform OS sandbox command construction for plugin workers."""

from __future__ import annotations

import json
import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PluginSandboxMode = Literal["auto", "required", "disabled"]


class PluginSandboxUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PluginSandboxStatus:
    mode: PluginSandboxMode
    backend: str | None
    enforced: bool


class PluginSandbox:
    def __init__(self, *, mode: PluginSandboxMode) -> None:
        self._mode = mode
        self._backend = None if mode == "disabled" else self._detect_backend()
        if mode == "required" and self._backend is None:
            raise PluginSandboxUnavailableError(
                "plugin OS sandbox is required but no supported backend is available"
            )

    @property
    def status(self) -> PluginSandboxStatus:
        return PluginSandboxStatus(
            mode=self._mode,
            backend=self._backend,
            enforced=self._backend is not None,
        )

    def command(
        self,
        *,
        worker_path: Path,
        plugin_root: Path,
        entrypoint: str,
    ) -> list[str]:
        python_binary = self._python_binary()
        worker_arguments = [
            str(python_binary),
            "-I",
            str(worker_path),
            "--plugin-dir",
            str(plugin_root),
            "--entrypoint",
            entrypoint,
        ]
        if self._backend == "sandbox-exec":
            return [
                "/usr/bin/sandbox-exec",
                "-p",
                self._macos_profile(
                    python_binary=python_binary,
                    worker_path=worker_path,
                    plugin_root=plugin_root,
                ),
                *worker_arguments,
            ]
        if self._backend == "bwrap":
            return self._bubblewrap_command(
                worker_arguments=worker_arguments,
                worker_path=worker_path,
                plugin_root=plugin_root,
            )
        return worker_arguments

    @staticmethod
    def _detect_backend() -> str | None:
        system = platform.system()
        if system == "Darwin" and Path("/usr/bin/sandbox-exec").is_file():
            return "sandbox-exec"
        if system == "Linux" and shutil.which("bwrap") is not None:
            return "bwrap"
        return None

    @staticmethod
    def _python_binary() -> Path:
        resolved = Path(sys.executable).resolve()
        if platform.system() != "Darwin":
            return resolved
        app_binary = (
            resolved.parent.parent
            / "Resources"
            / "Python.app"
            / "Contents"
            / "MacOS"
            / "Python"
        )
        return app_binary if app_binary.is_file() else resolved

    @staticmethod
    def _macos_profile(
        *,
        python_binary: Path,
        worker_path: Path,
        plugin_root: Path,
    ) -> str:
        def quote(value: Path) -> str:
            return json.dumps(str(value))

        denied_reads = [
            Path.home().resolve(),
            Path.cwd().resolve(),
            Path("/Volumes"),
            Path("/Network"),
            Path("/private/etc"),
            Path("/private/var"),
            Path("/private/tmp"),
        ]
        denied_rules = " ".join(
            f"(subpath {quote(path)})" for path in denied_reads
        )
        return " ".join(
            [
                "(version 1)",
                "(allow default)",
                "(deny network*)",
                "(deny file-write*)",
                "(deny process-fork)",
                "(deny process-exec)",
                f"(allow process-exec (literal {quote(python_binary)}))",
                f"(deny file-read* {denied_rules})",
                "(allow file-read* "
                f"(subpath {quote(worker_path.parent)}) "
                f"(subpath {quote(plugin_root)}))",
            ]
        )

    @staticmethod
    def _bubblewrap_command(
        *,
        worker_arguments: list[str],
        worker_path: Path,
        plugin_root: Path,
    ) -> list[str]:
        home = Path.home().resolve()
        return [
            "bwrap",
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--ro-bind",
            "/",
            "/",
            "--tmpfs",
            "/tmp",  # noqa: S108 - this is a private in-memory mount inside bwrap.
            "--tmpfs",
            str(home),
            "--dir",
            str(worker_path.parent),
            "--dir",
            str(plugin_root),
            "--ro-bind",
            str(worker_path.parent),
            str(worker_path.parent),
            "--ro-bind",
            str(plugin_root),
            str(plugin_root),
            "--",
            *worker_arguments,
        ]
