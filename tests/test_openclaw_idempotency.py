from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from living_agent.app import create_app
from living_agent.config import Settings

OPENCLAW_PATH = "/v1/adapters/openclaw/messages"
BRIDGE_TOKEN = "persistent-openclaw-idempotency-token"
AUTH_HEADERS = {"Authorization": f"Bearer {BRIDGE_TOKEN}"}
OWNER_HEADERS = {"X-Actor-ID": "owner-1"}


def configured_settings(settings: Settings) -> Settings:
    configured = settings.model_copy(deep=True)
    configured.openclaw_bridge_enabled = True
    configured.openclaw_bridge_access_token = SecretStr(BRIDGE_TOKEN)
    configured.openclaw_bridge_allowed_account_ids = ["wechat-account"]
    return configured


def payload(*, content: str = "hello") -> dict[str, object]:
    return {
        "protocol_version": 1,
        "channel_id": "openclaw-weixin",
        "account_id": "wechat-account",
        "conversation_id": "wechat-conversation",
        "sender_id": "wechat-user",
        "sender_name": "Friend",
        "message_id": "persistent-message-id",
        "content": content,
        "timestamp_ms": 1784540000000,
        "is_group": False,
        "session_key": "agent:main:openclaw-weixin:wechat-user",
        "run_id": "run-idempotency",
    }


def test_openclaw_message_replay_remains_suppressed_after_restart(
    settings: Settings,
) -> None:
    configured = configured_settings(settings)
    with TestClient(create_app(configured)) as first_client:
        first = first_client.post(OPENCLAW_PATH, headers=AUTH_HEADERS, json=payload())
        assert first.status_code == 200

    with TestClient(create_app(configured)) as second_client:
        replay = second_client.post(OPENCLAW_PATH, headers=AUTH_HEADERS, json=payload())
        conflict = second_client.post(
            OPENCLAW_PATH,
            headers=AUTH_HEADERS,
            json=payload(content="different content"),
        )
        audit = second_client.get("/v1/audit", headers=OWNER_HEADERS).json()

    assert replay.status_code == 200
    assert replay.json()["event_id"] == first.json()["event_id"]
    assert replay.json()["message"] is None
    assert replay.json()["messages"] == []
    assert replay.json()["utterance_session_id"] is None
    assert replay.json()["reason_code"] == "idempotent_replay"
    assert conflict.status_code == 409
    assert sum(entry["action"] == "event.ingested" for entry in audit) == 1
