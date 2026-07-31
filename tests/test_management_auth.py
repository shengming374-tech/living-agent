from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from living_agent.app import create_app
from living_agent.config import Settings
from living_agent.plugins.sandbox import PluginSandbox

MANAGEMENT_TOKEN = "management-test-token-with-32-characters"


def production_settings(settings: Settings) -> Settings:
    payload = settings.model_dump()
    payload.update(
        environment="production",
        management_api_token=SecretStr(MANAGEMENT_TOKEN),
    )
    return Settings.model_validate(payload)


def test_production_requires_management_token() -> None:
    with pytest.raises(
        ValidationError,
        match="management_api_token is required in production",
    ):
        Settings(environment="production")

    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(management_api_token=SecretStr("too-short"))


def test_production_rejects_missing_plugin_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(PluginSandbox, "_detect_backend", staticmethod(lambda: None))
    with pytest.raises(ValidationError, match="sandbox backend is required"):
        Settings(
            environment="production",
            management_api_token=SecretStr(MANAGEMENT_TOKEN),
        )


def test_management_api_requires_valid_bearer_token(settings: Settings) -> None:
    configured = production_settings(settings)
    with TestClient(create_app(configured)) as client:
        missing = client.get("/v1/audit", headers={"X-Actor-ID": "owner-1"})
        invalid = client.get(
            "/v1/audit",
            headers={
                "X-Actor-ID": "owner-1",
                "Authorization": "Bearer wrong-management-token-value",
            },
        )
        accepted = client.get(
            "/v1/audit",
            headers={
                "X-Actor-ID": "owner-1",
                "Authorization": f"Bearer {MANAGEMENT_TOKEN}",
            },
        )

    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert missing.json()["detail"] == "management_token_missing"
    assert invalid.status_code == 403
    assert invalid.json()["detail"] == "management_token_invalid"
    assert accepted.status_code == 200


def test_management_session_probes_authentication_and_authority(
    settings: Settings,
) -> None:
    configured = production_settings(settings)
    token_header = {"Authorization": f"Bearer {MANAGEMENT_TOKEN}"}
    with TestClient(create_app(configured)) as client:
        missing = client.get(
            "/v1/management/session",
            headers={"X-Actor-ID": "owner-1"},
        )
        owner = client.get(
            "/v1/management/session",
            headers={"X-Actor-ID": "owner-1", **token_header},
        )
        member = client.get(
            "/v1/management/session",
            headers={"X-Actor-ID": "member-1", **token_header},
        )

    assert missing.status_code == 401
    assert owner.json() == {
        "actor_id": "owner-1",
        "authority_level": "owner",
        "management_auth_required": True,
    }
    assert member.json()["authority_level"] == "member"


def test_platform_and_chat_ingress_keep_separate_auth_boundaries(settings: Settings) -> None:
    configured = production_settings(settings)
    with TestClient(create_app(configured)) as client:
        health = client.get("/health")
        chat = client.post(
            "/v1/chat",
            json={
                "content": "hello",
                "source_type": "direct_message",
                "source_identity": "member-1",
                "conversation_id": "conversation-1",
                "authenticated": True,
            },
        )
        adapter = client.post("/v1/adapters/openclaw/messages", json={})

    assert health.status_code == 200
    assert chat.status_code == 200
    assert adapter.status_code == 422
    assert adapter.json()["detail"] != "management_token_missing"
