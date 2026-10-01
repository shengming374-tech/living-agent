"""Direct chat identity claims require verified credentials before runtime effects."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from living_agent.app import create_app
from living_agent.config import Settings

TOKEN = "chat-auth-test-token-with-32-characters"
OWNER_HEADERS = {"X-Actor-ID": "owner-1", "Authorization": f"Bearer {TOKEN}"}


def _settings(settings: Settings, tmp_path: Path, *, environment: str = "production") -> Settings:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "private.txt").write_text("PRIVATE_LOCAL_TEST_MARKER", encoding="utf-8")
    (workspace / "README.md").write_text("# Local agent authentication test", encoding="utf-8")
    return settings.model_copy(
        update={
            "environment": environment,
            "management_api_token": SecretStr(TOKEN),
            "work_workspace_root": workspace,
        }
    )


def _envelope(content: str, *, authenticated: bool = True) -> dict[str, object]:
    return {
        "content": content,
        "source_type": "direct_message",
        "source_identity": "owner-1",
        "conversation_id": "chat-auth-test",
        "authenticated": authenticated,
    }


@pytest.mark.parametrize(
    "content",
    [
        "读取 private.txt",
        "创建文件 created.txt\uff1aUNAUTHORIZED_WRITE",
        "agent: 检查工作区并读取 README",
        "确认任务",
    ],
)
@pytest.mark.parametrize(
    ("authorization", "expected_status"),
    [(None, 401), ("Bearer invalid-test-token", 403)],
)
def test_production_owner_claim_is_rejected_before_runtime_effects(
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    authorization: str | None,
    expected_status: int,
) -> None:
    configured = _settings(settings, tmp_path)
    with TestClient(create_app(configured)) as client:
        runtime_call = AsyncMock(side_effect=AssertionError("unauthorized runtime was entered"))
        monkeypatch.setattr(client.app.state.runtime, "handle_platform_chat", runtime_call)
        headers = {"Authorization": authorization} if authorization is not None else {}
        denied = client.post("/v1/chat", headers=headers, json=_envelope(content))

        assert denied.status_code == expected_status
        if expected_status == 401:
            assert denied.headers["WWW-Authenticate"] == "Bearer"
        runtime_call.assert_not_called()
        assert client.get("/v1/tasks", headers=OWNER_HEADERS).json() == []
        assert client.get("/v1/agent/runs", headers=OWNER_HEADERS).json() == []
        assert client.get("/v1/users", headers=OWNER_HEADERS).json() == []
        events = client.portal.call(
            client.app.state.event_repository.recent_for_conversation, "chat-auth-test"
        )
        assert events == []
        assert not (configured.work_workspace_root / "created.txt").exists()


def test_configured_token_requires_credentials_in_development(
    settings: Settings, tmp_path: Path
) -> None:
    configured = _settings(settings, tmp_path, environment="development")
    with TestClient(create_app(configured)) as client:
        denied = client.post("/v1/chat", json=_envelope("读取 private.txt"))
        accepted = client.post(
            "/v1/chat", headers=OWNER_HEADERS, json=_envelope("读取 private.txt")
        )

    assert denied.status_code == 401
    assert accepted.status_code == 200
    assert "PRIVATE_LOCAL_TEST_MARKER" in accepted.json()["message"]


def test_production_valid_token_reads_and_confirms_write(
    settings: Settings, tmp_path: Path
) -> None:
    configured = _settings(settings, tmp_path)
    with TestClient(create_app(configured)) as client:
        read = client.post("/v1/chat", headers=OWNER_HEADERS, json=_envelope("读取 private.txt"))
        assert read.status_code == 200
        assert read.json()["event"]["authority_level"] == "owner"
        assert "PRIVATE_LOCAL_TEST_MARKER" in read.json()["message"]
        proposed = client.post(
            "/v1/chat", headers=OWNER_HEADERS,
            json=_envelope("创建文件 created.txt\uff1aAUTHORIZED_WRITE"),
        )
        assert proposed.status_code == 200
        assert not (configured.work_workspace_root / "created.txt").exists()
        tokenless_confirm = client.post("/v1/chat", json=_envelope("确认任务"))
        assert tokenless_confirm.status_code == 401
        assert not (configured.work_workspace_root / "created.txt").exists()
        confirmed = client.post("/v1/chat", headers=OWNER_HEADERS, json=_envelope("确认任务"))
        assert confirmed.status_code == 200
        assert (configured.work_workspace_root / "created.txt").read_text() == "AUTHORIZED_WRITE"


def test_production_valid_token_can_run_social_agent(settings: Settings, tmp_path: Path) -> None:
    configured = _settings(settings, tmp_path)
    with TestClient(create_app(configured)) as client:
        accepted = client.post(
            "/v1/chat", headers=OWNER_HEADERS,
            json=_envelope("agent: 检查工作区并读取 README"),
        )
        assert accepted.status_code == 200
        runs = client.get("/v1/agent/runs", headers=OWNER_HEADERS).json()
        assert len(runs) == 1
        assert runs[0]["status"] == "completed"


@pytest.mark.parametrize(
    "content",
    ["hello", "读取 private.txt", "agent: 检查工作区并读取 README", "确认任务"],
)
def test_unauthenticated_social_chat_cannot_claim_owner_authority(
    settings: Settings, tmp_path: Path, content: str
) -> None:
    configured = _settings(settings, tmp_path)
    with TestClient(create_app(configured)) as client:
        social = client.post("/v1/chat", json=_envelope(content, authenticated=False))
        assert social.status_code == 200
        assert social.json()["event"]["authority_level"] == "anonymous"
        assert "PRIVATE_LOCAL_TEST_MARKER" not in (social.json()["message"] or "")
        assert client.get("/v1/tasks", headers=OWNER_HEADERS).json() == []
        assert client.get("/v1/agent/runs", headers=OWNER_HEADERS).json() == []
