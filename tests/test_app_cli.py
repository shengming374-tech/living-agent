from __future__ import annotations

# ruff: noqa: S603 - all subprocess commands use the test interpreter and fixed entry point.
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from living_agent.cli.main import main, validate_url
from living_agent.cli.profile import ProfileLock, default_profile, initialize_profile
from living_agent.execution.work import WorkTaskExecutor


def test_profile_preserves_credentials_and_separates_workspace(tmp_path: Path) -> None:
    root = tmp_path / "应用数据 with spaces"
    first = initialize_profile(root)
    second = initialize_profile(root)
    assert first == second
    assert len(first.token) >= 32
    assert (root / "workspace").is_dir()
    if sys.platform != "win32":
        assert (root / "credentials.json").stat().st_mode & 0o077 == 0
    (root / "credentials.json").write_text("broken")
    with pytest.raises(ValueError):
        initialize_profile(root)


async def test_work_cancellation_terminates_real_process() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(60)",
        start_new_session=True,
    )
    try:
        await asyncio.wait_for(WorkTaskExecutor._terminate_process(process), timeout=5)
        assert process.returncode is not None
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def test_windows_and_macos_profile_locations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert default_profile() == tmp_path / "LivingAgent"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert default_profile() == Path.home() / "Library/Application Support/LivingAgent"


def test_profile_lock_rejects_second_runtime(tmp_path: Path) -> None:
    with ProfileLock(tmp_path), pytest.raises(RuntimeError), ProfileLock(tmp_path):
        pass


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:secret@example.com",
        "https://example.com/studio",
        "https://example.com?token=secret",
        "https://example.com/#foo",
        "file:///tmp/server",
    ],
)
def test_cli_rejects_insecure_or_credential_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_url(url)


def test_remote_connection_never_inherits_profile_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    initialize_profile(tmp_path)
    monkeypatch.delenv("LIVING_AGENT_CLIENT_TOKEN", raising=False)
    assert main(["--data-dir", str(tmp_path), "--url", "https://example.com", "status"]) == 1
    assert "LIVING_AGENT_CLIENT_TOKEN" in capsys.readouterr().err


def test_cli_runtime_clean_start_and_shutdown(tmp_path: Path) -> None:
    source = Path(__file__).resolve().parents[1] / "src"
    root = tmp_path / "运行时 with spaces"
    env = {key: value for key, value in os.environ.items() if not key.startswith("LIVING_AGENT_")}
    env["PYTHONPATH"] = str(source)
    command = [sys.executable, "-m", "living_agent", "--data-dir", str(root)]
    with (tmp_path / "server.log").open("w") as log:
        server = subprocess.Popen(
            [*command, "serve", "--port", "0"], cwd=tmp_path, env=env, stdout=log, stderr=log
        )
        try:
            for _ in range(300):
                if (root / "session.json").exists():
                    break
                if server.poll() is not None:
                    pytest.fail((tmp_path / "server.log").read_text())
                time.sleep(0.1)
            else:
                pytest.fail("runtime did not start")
            status = subprocess.run(
                [*command, "--json", "status"],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=True,
            )
            assert json.loads(status.stdout)["status"] == "ok"
            tools = subprocess.run(
                [*command, "--json", "tools"],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=True,
            )
            assert len(json.loads(tools.stdout)) == 11
            duplicate = subprocess.run(
                [*command, "serve", "--port", "0"],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            assert duplicate.returncode == 1
            assert "already running" in duplicate.stderr
            assert "token" not in status.stdout
        finally:
            if sys.platform == "win32":
                # Windows terminate is not SIGTERM / Windows 终止进程不触发 Unix 清理。
                server.kill()
            else:
                server.terminate()
            server.wait(timeout=20)
    if sys.platform != "win32":
        assert not (root / "session.json").exists()
    assert (root / "living-agent.sqlite3").is_file()
    assert not (tmp_path / "living_agent.db").exists()
