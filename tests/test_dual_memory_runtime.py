# ruff: noqa: RUF001

from __future__ import annotations

import json
from typing import Any, cast

from fastapi.testclient import TestClient

from living_agent.app import create_app
from living_agent.cognition.context_compiler import CompiledContext, ContextKind
from living_agent.config import Settings
from living_agent.providers.llm import ModelResponse

OWNER_HEADERS = {"X-Actor-ID": "owner-1"}
MEMBER_ID = "member-1"
CONVERSATION_ID = "dual-memory-chat"


class BranchingRecordingProvider:
    """Answer from fact cards only when the runtime actually injected one."""

    def __init__(self) -> None:
        self.contexts: list[CompiledContext] = []

    async def generate(self, context: CompiledContext) -> ModelResponse:
        self.contexts.append(context)
        fact_sections = [
            section
            for section in context.sections
            if section.kind is ContextKind.RETRIEVED_FACT
        ]
        if fact_sections:
            fact = json.loads(fact_sections[0].content)
            text = f"你叫{fact['value']}"
        else:
            text = "我不知道"
        return ModelResponse(text=text, provider="branching-recording")


def _chat(
    client: TestClient,
    content: str,
    *,
    conversation_id: str = CONVERSATION_ID,
) -> dict[str, Any]:
    response = client.post(
        "/v1/chat",
        json={
            "content": content,
            "source_type": "direct_message",
            "source_identity": MEMBER_ID,
            "conversation_id": conversation_id,
            "authenticated": True,
        },
    )
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


def _dual_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "memory_auto_candidates_enabled": True,
            "memory_auto_approval_enabled": True,
            "memory_recall_mode": "dual",
        }
    )


def _memories(client: TestClient) -> list[dict[str, Any]]:
    response = client.get("/v1/memories", headers=OWNER_HEADERS)
    assert response.status_code == 200
    return cast(list[dict[str, Any]], response.json())


def _pending_candidates(client: TestClient) -> list[dict[str, Any]]:
    response = client.get(
        "/v1/memories/candidates",
        params={"status": "pending"},
        headers=OWNER_HEADERS,
    )
    assert response.status_code == 200
    return cast(list[dict[str, Any]], response.json())


def _trace(client: TestClient, trace_id: object) -> dict[str, Any]:
    assert isinstance(trace_id, str)
    response = client.get(
        f"/v1/memories/traces/{trace_id}",
        headers=OWNER_HEADERS,
    )
    assert response.status_code == 200
    return cast(dict[str, Any], response.json())


def _memory_kinds(context: CompiledContext) -> list[ContextKind]:
    return [
        section.kind
        for section in context.sections
        if section.kind in {ContextKind.RETRIEVED_FACT, ContextKind.RETRIEVED_MEMORY}
    ]


def test_structured_name_fact_uses_exact_fact_trace_and_not_a_question_candidate(
    settings: Settings,
) -> None:
    provider = BranchingRecordingProvider()
    with TestClient(
        create_app(_dual_settings(settings), llm_provider=provider)
    ) as client:
        remembered = _chat(client, "记住，我叫盛茗")
        nodes = _memories(client)

        assert len(nodes) == 1
        memory = nodes[0]
        assert memory["memory_layer"] == "fact"
        assert memory["entity_id"] == MEMBER_ID
        assert memory["memory_key"] == "profile.name"
        assert memory["content"] == {
            "schema": "social.fact.v1",
            "key": "profile.name",
            "value": "盛茗",
            "cardinality": "single",
            "surface_text": "我叫盛茗",
        }
        assert memory["source_event_ids"] == [remembered["event"]["event_id"]]

        recalled = _chat(client, "我叫什么")
        recalled_context = provider.contexts[-1]
        trace = _trace(client, recalled["memory_trace_id"])

        assert recalled["recalled_memory_ids"] == [memory["id"]]
        assert recalled["memory_trace_id"]
        assert "盛茗" in str(recalled["message"])
        assert _memory_kinds(recalled_context) == [ContextKind.RETRIEVED_FACT]
        assert trace["trace"]["route"] == "exact_fact"
        assert trace["trace"]["support_mode"] in {"memory_only", "corroborated"}
        assert trace["items"][0]["memory_id"] == memory["id"]
        assert trace["items"][0]["injected"] is True
        assert trace["items"][0]["response_match"] is True
        assert _pending_candidates(client) == []


def test_unrelated_desktop_shell_query_is_not_injected(
    settings: Settings,
) -> None:
    provider = BranchingRecordingProvider()
    with TestClient(
        create_app(_dual_settings(settings), llm_provider=provider)
    ) as client:
        _chat(client, "记住，我叫盛茗")
        unrelated = _chat(client, "桌面上有什么？调用 shell 去看看")
        unrelated_context = provider.contexts[-1]
        trace = _trace(client, unrelated["memory_trace_id"])

        assert unrelated["recalled_memory_ids"] == []
        assert _memory_kinds(unrelated_context) == []
        assert trace["trace"]["route"] == "none"
        assert trace["trace"]["support_mode"] == "not_injected"
        assert trace["items"] == []


def test_owner_probe_makes_exactly_two_isolated_model_calls(
    settings: Settings,
) -> None:
    provider = BranchingRecordingProvider()
    with TestClient(
        create_app(_dual_settings(settings), llm_provider=provider)
    ) as client:
        _chat(client, "记住，我叫盛茗")
        memory = _memories(client)[0]
        calls_before_probe = len(provider.contexts)

        response = client.post(
            "/v1/memories/probe",
            headers=OWNER_HEADERS,
            json={
                "subject_id": MEMBER_ID,
                "prompt": "我叫什么",
                "fact_keys": ["profile.name"],
            },
        )

        assert response.status_code == 200
        result = response.json()
        probe_contexts = provider.contexts[calls_before_probe:]
        assert len(probe_contexts) == 2
        assert _memory_kinds(probe_contexts[0]) == [ContextKind.RETRIEVED_FACT]
        assert _memory_kinds(probe_contexts[1]) == []
        assert result["verdict"] == "supported"
        assert result["support_mode"] == "memory_only"
        assert result["with_memory"]["text"] == "你叫盛茗"
        assert result["with_memory"]["selected_memory_ids"] == [memory["id"]]
        assert result["without_memory"]["text"] == "我不知道"
        assert result["without_memory"]["selected_memory_ids"] == []
        assert result["trace_id"]


def test_non_owner_cannot_run_memory_probe(settings: Settings) -> None:
    provider = BranchingRecordingProvider()
    with TestClient(
        create_app(_dual_settings(settings), llm_provider=provider)
    ) as client:
        calls_before_probe = len(provider.contexts)
        response = client.post(
            "/v1/memories/probe",
            headers={"X-Actor-ID": MEMBER_ID},
            json={
                "subject_id": MEMBER_ID,
                "prompt": "我叫什么",
                "fact_keys": ["profile.name"],
            },
        )

        assert response.status_code == 403
        assert len(provider.contexts) == calls_before_probe


def test_duplicate_self_report_confirms_same_node_and_deduplicates_sources(
    settings: Settings,
) -> None:
    provider = BranchingRecordingProvider()
    with TestClient(
        create_app(_dual_settings(settings), llm_provider=provider)
    ) as client:
        first = _chat(client, "我叫盛茗")
        original = _memories(client)[0]

        repeated = _chat(client, "我叫盛茗")
        confirmed = _memories(client)[0]

        assert confirmed["id"] == original["id"]
        assert confirmed["version"] == int(original["version"]) + 1
        assert confirmed["source_event_ids"] == [
            first["event"]["event_id"],
            repeated["event"]["event_id"],
        ]
        assert len(confirmed["source_event_ids"]) == len(
            set(confirmed["source_event_ids"])
        )
        assert _pending_candidates(client) == []


def test_explicit_name_correction_updates_the_same_fact_node(
    settings: Settings,
) -> None:
    provider = BranchingRecordingProvider()
    with TestClient(
        create_app(_dual_settings(settings), llm_provider=provider)
    ) as client:
        _chat(client, "我叫盛茗")
        original = _memories(client)[0]

        corrected_event = _chat(client, "我现在叫新名")
        corrected = _memories(client)[0]

        assert corrected["id"] == original["id"]
        assert corrected["version"] == int(original["version"]) + 1
        assert corrected["content"]["value"] == "新名"
        assert corrected["content"]["surface_text"] == "我现在叫新名"
        assert corrected["source_event_ids"][-1] == corrected_event["event"]["event_id"]
        assert _pending_candidates(client) == []


def test_ordinary_contradictory_name_stays_pending_for_review(
    settings: Settings,
) -> None:
    provider = BranchingRecordingProvider()
    with TestClient(
        create_app(_dual_settings(settings), llm_provider=provider)
    ) as client:
        _chat(client, "我叫盛茗")
        original = _memories(client)[0]

        conflicting_event = _chat(client, "我叫另一名")
        active = _memories(client)
        pending = _pending_candidates(client)

        assert active == [original]
        assert len(pending) == 1
        assert pending[0]["content"]["value"] == "另一名"
        assert pending[0]["memory_layer"] == "fact"
        assert pending[0]["memory_key"] == "profile.name"
        assert pending[0]["decision_reason"] == "conflicting_memory_requires_review"
        assert pending[0]["source_event_ids"] == [
            conflicting_event["event"]["event_id"]
        ]


def test_explicit_forget_soft_deletes_fact_and_prevents_recall(
    settings: Settings,
) -> None:
    provider = BranchingRecordingProvider()
    with TestClient(
        create_app(_dual_settings(settings), llm_provider=provider)
    ) as client:
        _chat(client, "我叫盛茗")
        original = _memories(client)[0]

        _chat(client, "请忘记我的名字")
        active = _memories(client)
        deleted = client.get(
            "/v1/memories?include_deleted=true&limit=20",
            headers=OWNER_HEADERS,
        ).json()
        recalled = _chat(client, "我叫什么")
        trace = _trace(client, recalled["memory_trace_id"])

        assert active == []
        assert len(deleted) == 1
        assert deleted[0]["id"] == original["id"]
        assert deleted[0]["status"] == "deleted"
        assert deleted[0]["version"] == int(original["version"]) + 1
        assert recalled["recalled_memory_ids"] == []
        assert trace["trace"]["route"] == "exact_fact"
        assert trace["trace"]["support_mode"] == "not_injected"
