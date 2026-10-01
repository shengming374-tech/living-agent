"""Embedded option paths cannot write outside the configured workspace."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from living_agent.app import create_app
from living_agent.config import Settings


@pytest.mark.parametrize("kind", ["absolute", "parent", "symlink", "sensitive"])
def test_confirmed_git_output_stays_inside_scope(
    settings: Settings, tmp_path: Path, kind: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("before\n")
    (workspace / "b.txt").write_text("after\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("preserve")
    (workspace / "escape").symlink_to(tmp_path, target_is_directory=True)
    paths = {
        "absolute": str(outside),
        "parent": "../outside.txt",
        "symlink": "escape/outside.txt",
        "sensitive": ".env",
    }
    configured = settings.model_copy(update={"work_workspace_root": workspace})
    with TestClient(create_app(configured)) as client:
        envelope = {
            "content": f"运行命令 `git diff --no-index --output={paths[kind]} a.txt b.txt`",
            "source_type": "direct_message",
            "source_identity": "owner-1",
            "authenticated": True,
            "conversation_id": "shell-scope",
        }
        assert client.post("/v1/chat", json=envelope).status_code == 200
        envelope["content"] = "确认任务"
        assert client.post("/v1/chat", json=envelope).status_code == 200
        task = client.get("/v1/tasks", headers={"X-Actor-ID": "owner-1"}).json()[0]
        assert task["status"] == "failed"
        assert task["step_results"][0]["errors"] == ["shell_argument_scope_denied"]
    assert outside.read_text() == "preserve"
    assert not (workspace / ".env").exists()


def test_confirmed_relative_git_output_remains_usable(settings: Settings, tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("before\n")
    (workspace / "b.txt").write_text("after\n")
    configured = settings.model_copy(update={"work_workspace_root": workspace})
    with TestClient(create_app(configured)) as client:
        envelope = {
            "content": "运行命令 `git diff --no-index --output=result.diff a.txt b.txt`",
            "source_type": "direct_message",
            "source_identity": "owner-1",
            "authenticated": True,
            "conversation_id": "shell-scope",
        }
        assert client.post("/v1/chat", json=envelope).status_code == 200
        assert not (workspace / "result.diff").exists()
        envelope["content"] = "确认任务"
        assert client.post("/v1/chat", json=envelope).status_code == 200
    assert "+after" in (workspace / "result.diff").read_text()
