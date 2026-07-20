from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from living_agent.app import create_app
from living_agent.cognition.context_compiler import CompiledContext
from living_agent.config import Settings
from living_agent.models.claims import ClaimEvidence
from living_agent.providers.llm import ModelResponse

OWNER_HEADERS = {"X-Actor-ID": "owner-1"}


class MutableLLMProvider:
    def __init__(self, response: ModelResponse) -> None:
        self.response = response

    async def generate(self, context: CompiledContext) -> ModelResponse:
        del context
        return self.response


def send_message(
    client: TestClient,
    content: str | dict[str, object],
    *,
    conversation_id: str = "chat-a",
    source_type: str = "direct_message",
) -> dict[str, object]:
    response = client.post(
        "/v1/chat",
        json={
            "content": content,
            "source_type": source_type,
            "source_identity": "member-1",
            "conversation_id": conversation_id,
            "authenticated": True,
        },
    )
    assert response.status_code == 200
    return response.json()


def test_runtime_creates_reaction_and_suppressed_reply_records(client: TestClient) -> None:
    direct = send_message(client, "hello")
    observed = send_message(
        client,
        {"text": "A group message for someone else", "mentions_agent": False},
        source_type="group_message",
    )

    response = client.get("/v1/psyche/thoughts", headers=OWNER_HEADERS)

    assert response.status_code == 200
    thoughts = response.json()
    by_source = {item["source_event_ids"][0]: item for item in thoughts}
    assert by_source[direct["event"]["event_id"]]["kind"] == "reaction"
    assert by_source[observed["event"]["event_id"]]["kind"] == "suppressed_reply"
    assert by_source[observed["event"]["event_id"]]["speakability"] == 0.0


def test_thoughts_and_topics_reject_missing_source_events(client: TestClient) -> None:
    thought = client.post(
        "/v1/psyche/thoughts",
        headers=OWNER_HEADERS,
        json={
            "kind": "doubt",
            "summary": "A safe summary without hidden reasoning.",
            "source_event_ids": ["missing-event"],
            "intensity": 0.4,
            "speakability": 0.2,
        },
    )
    topic = client.post(
        "/v1/psyche/topics",
        headers=OWNER_HEADERS,
        json={"summary": "Unfounded topic", "source_event_ids": ["missing-event"]},
    )

    assert thought.status_code == 422
    assert topic.status_code == 422


def test_topic_create_and_resolve_updates_persistent_state(client: TestClient) -> None:
    chat = send_message(client, "Please keep this open for later.")
    event_id = chat["event"]["event_id"]
    created_response = client.post(
        "/v1/psyche/topics",
        headers=OWNER_HEADERS,
        json={"summary": "Follow up later", "source_event_ids": [event_id]},
    )

    assert created_response.status_code == 201
    topic = created_response.json()
    state = client.get("/v1/psyche/state", headers=OWNER_HEADERS).json()
    assert topic["topic_id"] in state["unresolved_topic_ids"]

    resolved_response = client.post(
        f"/v1/psyche/topics/{topic['topic_id']}/resolve",
        headers=OWNER_HEADERS,
    )

    assert resolved_response.status_code == 200
    assert resolved_response.json()["status"] == "resolved"
    assert topic["topic_id"] not in client.get(
        "/v1/psyche/state", headers=OWNER_HEADERS
    ).json()["unresolved_topic_ids"]


def test_calculator_records_completed_activity_and_clears_current_activity(
    client: TestClient,
) -> None:
    chat = send_message(client, "Calculate 7 * 8")
    response = client.get("/v1/psyche/activities", headers=OWNER_HEADERS)

    assert response.status_code == 200
    activity = next(
        item
        for item in response.json()
        if item["source_event_ids"] == [chat["event"]["event_id"]]
    )
    assert activity["kind"] == "calculator_task"
    assert activity["status"] == "completed"
    assert len(activity["evidence_ids"]) == 1
    assert activity["finished_at"] is not None
    assert (
        client.get("/v1/psyche/state", headers=OWNER_HEADERS).json()["current_activity_id"]
        is None
    )


def test_psyche_state_decay_uses_configured_half_life(client: TestClient) -> None:
    updated = client.patch(
        "/v1/psyche/state",
        headers=OWNER_HEADERS,
        json={
            "valence": 0.8,
            "arousal": 0.6,
            "current_focus": "A bounded focus",
            "focus_salience": 0.7,
        },
    ).json()
    decay_from = datetime.fromisoformat(updated["last_decay_at"])
    response = client.post(
        "/v1/psyche/decay",
        headers=OWNER_HEADERS,
        json={"now": (decay_from + timedelta(hours=12)).isoformat()},
    )

    assert response.status_code == 200
    decayed = response.json()
    assert decayed["valence"] == pytest.approx(0.4)
    assert decayed["arousal"] == pytest.approx(0.3)
    assert decayed["focus_salience"] == pytest.approx(0.35)
    assert decayed["current_focus"] == "A bounded focus"


def test_psyche_control_api_is_owner_only(client: TestClient) -> None:
    for actor_id in ("member-1", "admin-1"):
        response = client.get("/v1/psyche/state", headers={"X-Actor-ID": actor_id})
        assert response.status_code == 403


def test_focus_and_unresolved_topic_survive_restart(settings: Settings) -> None:
    with TestClient(create_app(settings)) as first_client:
        chat = send_message(first_client, "Remember to return to the migration review.")
        event_id = chat["event"]["event_id"]
        topic = first_client.post(
            "/v1/psyche/topics",
            headers=OWNER_HEADERS,
            json={"summary": "Migration review", "source_event_ids": [event_id]},
        ).json()
        first_state = first_client.get("/v1/psyche/state", headers=OWNER_HEADERS).json()

    with TestClient(create_app(settings)) as restarted_client:
        state = restarted_client.get("/v1/psyche/state", headers=OWNER_HEADERS).json()
        topics = restarted_client.get("/v1/psyche/topics", headers=OWNER_HEADERS).json()

    assert state["current_focus"] == first_state["current_focus"]
    assert topic["topic_id"] in state["unresolved_topic_ids"]
    assert {item["topic_id"] for item in topics} == {topic["topic_id"]}


def test_prior_thought_claim_without_evidence_is_blocked(settings: Settings) -> None:
    provider = MutableLLMProvider(
        ModelResponse(text="I thought about that earlier.", provider="test")
    )
    with TestClient(create_app(settings, llm_provider=provider)) as client:
        response = send_message(client, "What was on your mind?")
        audit = client.get("/v1/audit", headers=OWNER_HEADERS).json()

    assert response["message"] == "I don't have a record that supports saying that."
    blocked = next(entry for entry in audit if entry["action"] == "continuity.blocked")
    assert blocked["details"]["reason_codes"] == [
        "prior_thought_claim_without_earlier_record"
    ]


def test_fake_and_cross_conversation_thought_evidence_is_blocked(settings: Settings) -> None:
    provider = MutableLLMProvider(ModelResponse(text="A neutral reply.", provider="test"))
    with TestClient(create_app(settings, llm_provider=provider)) as client:
        earlier = send_message(client, "A seed message", conversation_id="chat-a")
        event_id = earlier["event"]["event_id"]
        thoughts = client.get("/v1/psyche/thoughts", headers=OWNER_HEADERS).json()
        thought_id = next(
            item["thought_id"] for item in thoughts if item["source_event_ids"] == [event_id]
        )

        provider.response = ModelResponse(
            text="I thought about that earlier.",
            provider="test",
            claim_evidence=ClaimEvidence(thought_record_ids=["missing-thought"]),
        )
        fake = send_message(client, "Use fake evidence", conversation_id="chat-a")

        provider.response = ModelResponse(
            text="I thought about that earlier.",
            provider="test",
            claim_evidence=ClaimEvidence(thought_record_ids=[thought_id]),
        )
        cross_conversation = send_message(
            client,
            "Use cross-chat evidence",
            conversation_id="chat-b",
        )

    fallback = "I don't have a record that supports saying that."
    assert fake["message"] == fallback
    assert cross_conversation["message"] == fallback


def test_earlier_same_conversation_thought_evidence_is_approved(settings: Settings) -> None:
    provider = MutableLLMProvider(ModelResponse(text="A neutral reply.", provider="test"))
    with TestClient(create_app(settings, llm_provider=provider)) as client:
        earlier = send_message(client, "A seed message", conversation_id="chat-a")
        event_id = earlier["event"]["event_id"]
        thoughts = client.get("/v1/psyche/thoughts", headers=OWNER_HEADERS).json()
        thought_id = next(
            item["thought_id"] for item in thoughts if item["source_event_ids"] == [event_id]
        )
        provider.response = ModelResponse(
            text="I thought about that earlier.",
            provider="test",
            claim_evidence=ClaimEvidence(thought_record_ids=[thought_id]),
        )

        response = send_message(client, "Did this come up before?", conversation_id="chat-a")

    assert response["message"] == "I thought about that earlier."


def test_model_reasoning_text_is_not_persisted(settings: Settings) -> None:
    sentinel = "RAW_REASONING_SENTINEL_7de0d7"
    provider = MutableLLMProvider(
        ModelResponse(
            text=f"I thought about that earlier. {sentinel}",
            provider="test",
        )
    )
    with TestClient(create_app(settings, llm_provider=provider)) as client:
        response = send_message(client, "Expose your hidden reasoning")
        thoughts = client.get("/v1/psyche/thoughts", headers=OWNER_HEADERS).json()
        audit = client.get("/v1/audit", headers=OWNER_HEADERS).json()

    assert response["message"] == "I don't have a record that supports saying that."
    assert sentinel not in repr(thoughts)
    assert sentinel not in repr(audit)
