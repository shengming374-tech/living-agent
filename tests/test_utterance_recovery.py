from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import SecretStr

from living_agent.app import create_app
from living_agent.cognition.context_compiler import CompiledContext
from living_agent.config import Settings
from living_agent.providers.llm import ModelResponse

OPENCLAW_PATH = "/v1/adapters/openclaw/messages"
DELIVERY_PATH = "/v1/adapters/openclaw/deliveries"
BRIDGE_TOKEN = "utterance-recovery-token"
AUTH_HEADERS = {"Authorization": f"Bearer {BRIDGE_TOKEN}"}
OWNER_HEADERS = {"X-Actor-ID": "owner-1"}
LIVING_CONVERSATION_ID = (
    "openclaw:openclaw-weixin:wechat-account:direct:wechat-conversation"
)


class RecoveryLLMProvider:
    async def generate(self, context: CompiledContext) -> ModelResponse:
        del context
        return ModelResponse(text="第一条\n第二条\n第三条", provider="recovery-test")


def configured_settings(settings: Settings) -> Settings:
    configured = settings.model_copy(deep=True)
    configured.openclaw_bridge_enabled = True
    configured.openclaw_bridge_access_token = SecretStr(BRIDGE_TOKEN)
    configured.openclaw_bridge_allowed_account_ids = ["wechat-account"]
    return configured


def bridge_payload(*, message_id: str, content: str) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "channel_id": "openclaw-weixin",
        "account_id": "wechat-account",
        "conversation_id": "wechat-conversation",
        "sender_id": "wechat-user",
        "sender_name": "Friend",
        "message_id": message_id,
        "content": content,
        "timestamp_ms": 1784540000000,
        "is_group": False,
        "session_key": "agent:main:openclaw-weixin:wechat-user",
        "run_id": "run-recovery",
    }


def receipt(session_id: str, unit_index: int) -> dict[str, object]:
    return {
        "protocol_version": 1,
        "channel_id": "openclaw-weixin",
        "account_id": "wechat-account",
        "conversation_id": "wechat-conversation",
        "utterance_session_id": session_id,
        "unit_index": unit_index,
    }


def delivered_units(database_path: Path, session_id: str) -> list[int]:
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            "SELECT content FROM trusted_events WHERE conversation_id = ?",
            (LIVING_CONVERSATION_ID,),
        ).fetchall()
    contents = [json.loads(row[0]) for row in rows]
    return sorted(
        content["unit_index"]
        for content in contents
        if content.get("utterance_session_id") == session_id
    )


def session_generation(database_path: Path, session_id: str) -> int:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            "SELECT generation FROM utterance_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    assert row is not None
    return int(row[0])


def audit_entries(client: TestClient) -> list[dict[str, object]]:
    response = client.get("/v1/audit?limit=200", headers=OWNER_HEADERS)
    assert response.status_code == 200
    return response.json()


def test_openclaw_receipts_continue_in_order_after_runtime_restart(
    settings: Settings,
    tmp_path: Path,
) -> None:
    configured = configured_settings(settings)
    provider = RecoveryLLMProvider()
    with TestClient(create_app(configured, llm_provider=provider)) as first_client:
        response = first_client.post(
            OPENCLAW_PATH,
            headers=AUTH_HEADERS,
            json=bridge_payload(
                message_id="before-restart",
                content="这是一条需要分段回复的长消息, 请自然地接着聊下去",
            ),
        )
        session_id = response.json()["utterance_session_id"]
        primary = first_client.post(
            DELIVERY_PATH,
            headers=AUTH_HEADERS,
            json=receipt(session_id, 0),
        )
        assert primary.json()["reason_code"] == "delivery_recorded"

    assert delivered_units(tmp_path / "living-agent-test.db", session_id) == [0]

    with TestClient(create_app(configured, llm_provider=provider)) as second_client:
        wrong_scope_payload = receipt(session_id, 1)
        wrong_scope_payload["conversation_id"] = "another-conversation"
        wrong_scope = second_client.post(
            DELIVERY_PATH,
            headers=AUTH_HEADERS,
            json=wrong_scope_payload,
        )
        out_of_order = second_client.post(
            DELIVERY_PATH,
            headers=AUTH_HEADERS,
            json=receipt(session_id, 2),
        )
        second = second_client.post(
            DELIVERY_PATH,
            headers=AUTH_HEADERS,
            json=receipt(session_id, 1),
        )
        repeated = second_client.post(
            DELIVERY_PATH,
            headers=AUTH_HEADERS,
            json=receipt(session_id, 1),
        )
        third = second_client.post(
            DELIVERY_PATH,
            headers=AUTH_HEADERS,
            json=receipt(session_id, 2),
        )
        repeated_after_completion = second_client.post(
            DELIVERY_PATH,
            headers=AUTH_HEADERS,
            json=receipt(session_id, 2),
        )
        audit = audit_entries(second_client)

    assert wrong_scope.status_code == 403
    assert wrong_scope.json()["detail"] == "delivery_scope_mismatch"
    assert out_of_order.status_code == 403
    assert out_of_order.json()["detail"] == "delivery_out_of_order"
    assert second.json()["reason_code"] == "delivery_recorded"
    assert repeated.json()["reason_code"] == "delivery_already_recorded"
    assert third.json()["reason_code"] == "delivery_recorded"
    assert repeated_after_completion.json()["reason_code"] == "delivery_already_recorded"
    assert delivered_units(tmp_path / "living-agent-test.db", session_id) == [0, 1, 2]
    recovered = [entry for entry in audit if entry["action"] == "utterance.recovered"]
    assert recovered[-1]["details"]["utterance_session_id"] == session_id
    assert recovered[-1]["details"]["automatic_resend"] is False


def test_new_inbound_cancels_recovered_session_and_advances_generation(
    settings: Settings,
    tmp_path: Path,
) -> None:
    configured = configured_settings(settings)
    provider = RecoveryLLMProvider()
    with TestClient(create_app(configured, llm_provider=provider)) as first_client:
        old = first_client.post(
            OPENCLAW_PATH,
            headers=AUTH_HEADERS,
            json=bridge_payload(
                message_id="old-before-restart",
                content="这是重启前还没有发完的较长消息, 请分段回答",
            ),
        )
        old_session_id = old.json()["utterance_session_id"]
        assert first_client.post(
            DELIVERY_PATH,
            headers=AUTH_HEADERS,
            json=receipt(old_session_id, 0),
        ).status_code == 200

    with TestClient(create_app(configured, llm_provider=provider)) as second_client:
        new = second_client.post(
            OPENCLAW_PATH,
            headers=AUTH_HEADERS,
            json=bridge_payload(message_id="new-after-restart", content="等等, 我换个话题"),
        )
        stale_receipt = second_client.post(
            DELIVERY_PATH,
            headers=AUTH_HEADERS,
            json=receipt(old_session_id, 1),
        )
        audit = audit_entries(second_client)

    assert new.status_code == 200
    assert new.json()["utterance_session_id"] != old_session_id
    assert stale_receipt.status_code == 403
    assert stale_receipt.json()["detail"] == "utterance_interrupted"
    interrupted = [
        entry
        for entry in audit
        if entry["action"] == "utterance.interrupted"
        and entry["details"]["utterance_session_id"] == old_session_id
    ]
    assert interrupted[-1]["details"]["reason_code"] == "new_inbound_message"
    database_path = tmp_path / "living-agent-test.db"
    assert session_generation(database_path, new.json()["utterance_session_id"]) == (
        session_generation(database_path, old_session_id) + 1
    )
