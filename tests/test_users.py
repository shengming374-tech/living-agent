from fastapi.testclient import TestClient


def _chat(
    client: TestClient,
    *,
    source_identity: str | None,
    display_name: str | None,
    authenticated: bool,
    source_type: str = "direct_message",
) -> None:
    response = client.post(
        "/v1/chat",
        json={
            "content": "你好",
            "source_type": source_type,
            "source_identity": source_identity,
            "display_name": display_name,
            "conversation_id": "conversation-1",
            "authenticated": authenticated,
        },
    )
    assert response.status_code == 200


def test_authenticated_social_message_registers_stable_user(client: TestClient) -> None:
    _chat(
        client,
        source_identity="napcat:10001:qq:20002",
        display_name="小明",
        authenticated=True,
    )

    response = client.get("/v1/users", headers={"X-Actor-ID": "owner-1"})

    assert response.status_code == 200
    assert response.json()[0] == {
        "user_id": "napcat:10001:qq:20002",
        "display_name": "小明",
        "source_type": "direct_message",
        "first_seen_at": response.json()[0]["first_seen_at"],
        "last_seen_at": response.json()[0]["last_seen_at"],
        "message_count": 1,
        "last_conversation_id": "conversation-1",
    }


def test_second_message_updates_profile_without_changing_authority(client: TestClient) -> None:
    _chat(
        client,
        source_identity="member-7",
        display_name="Owner",
        authenticated=True,
    )
    _chat(
        client,
        source_identity="member-7",
        display_name="新昵称",
        authenticated=True,
        source_type="group_message",
    )

    response = client.get("/v1/users/member-7", headers={"X-Actor-ID": "owner-1"})

    assert response.status_code == 200
    assert response.json()["display_name"] == "新昵称"
    assert response.json()["message_count"] == 2
    assert response.json()["source_type"] == "group_message"
    audit = client.get("/v1/audit", headers={"X-Actor-ID": "owner-1"}).json()
    registration = next(entry for entry in audit if entry["action"] == "user.registered")
    assert registration["actor_id"] == "member-7"
    assert "display_name" not in registration["details"]


def test_unauthenticated_message_does_not_register_user(client: TestClient) -> None:
    _chat(
        client,
        source_identity="claimed-owner",
        display_name="Owner",
        authenticated=False,
    )

    response = client.get("/v1/users", headers={"X-Actor-ID": "owner-1"})

    assert response.status_code == 200
    assert response.json() == []


def test_registered_users_are_owner_only(client: TestClient) -> None:
    _chat(
        client,
        source_identity="member-1",
        display_name="Member",
        authenticated=True,
    )

    denied = client.get("/v1/users", headers={"X-Actor-ID": "member-1"})
    missing = client.get("/v1/users/unknown", headers={"X-Actor-ID": "owner-1"})

    assert denied.status_code == 403
    assert missing.status_code == 404
