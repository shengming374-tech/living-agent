from __future__ import annotations

import asyncio
import time

from fastapi.testclient import TestClient

from living_agent.app import create_app
from living_agent.cognition.context_compiler import CompiledContext, ContextKind
from living_agent.config import Settings
from living_agent.providers.llm import ModelResponse

HEADERS = {"X-Actor-ID": "owner-1"}
MEMBERS = [
    {"name": "探索者", "persona": "好奇, 提出新想法"},
    {"name": "审阅者", "persona": "冷静, 重视证据"},
]


def create_room(client: TestClient) -> dict:
    response = client.post("/v1/groups", headers=HEADERS, json={"name": "圆桌", "members": MEMBERS})
    assert response.status_code == 200
    return response.json()


def settle(client: TestClient, room_id: str) -> dict:
    for _ in range(200):
        room = client.get(f"/v1/groups/{room_id}", headers=HEADERS).json()
        if room["status"] != "responding":
            return room
        time.sleep(0.01)
    raise AssertionError("group did not settle")


def test_group_members_reply_and_history_survives_restart(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        room = create_room(client)
        room_id = room["room_id"]
        sent = client.post(
            f"/v1/groups/{room_id}/messages", headers=HEADERS, json={"content": "如何改进计划?"}
        )
        assert sent.status_code == 200
        finished = settle(client, room_id)
        assert finished["status"] == "idle"
        assert [message["speaker_name"] for message in finished["messages"]] == [
            "我",
            "探索者",
            "审阅者",
        ]
        assert all("演示" in message["content"] for message in finished["messages"][1:])
        assert client.get("/v1/agent/runs", headers=HEADERS).json() == []
    with TestClient(create_app(settings)) as client:
        assert (
            client.get(f"/v1/groups/{room_id}", headers=HEADERS).json()["messages"]
            == finished["messages"]
        )


def test_group_mentions_and_validation(client: TestClient) -> None:
    room = create_room(client)
    path = f"/v1/groups/{room['room_id']}/messages"
    assert (
        client.post(
            path, headers=HEADERS, json={"content": "hi", "mentions": ["missing"]}
        ).status_code
        == 400
    )
    assert client.post(path, headers=HEADERS, json={"content": " "}).status_code == 422
    assert (
        client.post(
            path,
            headers=HEADERS,
            json={"content": "你好", "mentions": [room["members"][1]["member_id"]]},
        ).status_code
        == 200
    )
    result = settle(client, room["room_id"])
    assert [message["speaker_name"] for message in result["messages"]] == ["我", "审阅者"]
    assert client.get("/v1/groups", headers={"X-Actor-ID": "admin-1"}).status_code == 403
    assert client.get("/v1/groups/missing", headers=HEADERS).status_code == 404
    assert (
        client.post(
            "/v1/groups", headers=HEADERS, json={"name": "bad", "members": [MEMBERS[0], MEMBERS[0]]}
        ).status_code
        == 422
    )


class BlockingModel:
    async def generate(self, context: CompiledContext) -> ModelResponse:
        assert context.sections[0].kind == ContextKind.ROOT_POLICY
        assert "群聊内容" in context.sections[0].content
        assert context.sections[1].kind == ContextKind.INTERACTION_PLAN
        assert "untrusted_input" in context.sections[2].taint_labels
        await asyncio.sleep(60)
        return ModelResponse(text="不应出现", provider="test")


def test_group_stop_cancels_model_and_preserves_owner_message(client: TestClient) -> None:
    client.app.state.group_service._llm = BlockingModel()
    room = create_room(client)
    path = f"/v1/groups/{room['room_id']}"
    assert (
        client.post(path + "/messages", headers=HEADERS, json={"content": "start"}).status_code
        == 200
    )
    assert (
        client.post(path + "/messages", headers=HEADERS, json={"content": "duplicate"}).status_code
        == 409
    )
    stopped = client.post(path + "/stop", headers=HEADERS).json()
    assert stopped["status"] == "stopped"
    assert len(stopped["messages"]) == 1
    assert not client.app.state.group_service._tasks


def test_owner_chat_history_auth_and_persistence(client: TestClient) -> None:
    sent = client.post(
        "/v1/chat",
        json={
            "content": "你好",
            "source_type": "direct_message",
            "source_identity": "owner-1",
            "authenticated": True,
            "conversation_id": "app-test",
        },
    )
    assert sent.status_code == 200
    response = client.get("/v1/chat/history?conversation_id=app-test", headers=HEADERS)
    assert response.status_code == 200
    assert any(item["event_type"] == "agent.response" for item in response.json())
    assert (
        client.get(
            "/v1/chat/history?conversation_id=app-test", headers={"X-Actor-ID": "admin-1"}
        ).status_code
        == 403
    )
