import asyncio
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from living_agent.app import create_app
from living_agent.cognition.context_compiler import CompiledContext, ContextKind
from living_agent.config import Settings
from living_agent.models.events import IngressEnvelope, SourceType
from living_agent.providers.llm import ModelResponse


class RecordingProvider:
    def __init__(self) -> None:
        self.contexts: list[CompiledContext] = []

    async def generate(self, context: CompiledContext) -> ModelResponse:
        self.contexts.append(context)
        return ModelResponse(text="自然回复", provider="recording", model="recording-v1")


class BlockingProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def generate(self, context: CompiledContext) -> ModelResponse:
        del context
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return ModelResponse(text="过期回复", provider="blocking", model="blocking-v1")


async def test_group_auto_participation_does_not_cancel_in_flight_model_plan(
    settings: Settings,
) -> None:
    provider = BlockingProvider()
    configured = settings.model_copy(
        update={
            "social_group_auto_participation": True,
            "social_group_min_user_turns": 1,
            "social_group_cooldown_seconds": 0.0,
        }
    )

    def group_message(text: str) -> IngressEnvelope:
        return IngressEnvelope(
            content={"text": text, "mentions_agent": False, "mentions_other": False},
            source_type=SourceType.GROUP_MESSAGE,
            source_identity="member-1",
            conversation_id="busy-group",
            authenticated=True,
        )

    with TestClient(create_app(configured, llm_provider=provider)) as client:
        runtime = client.app.state.runtime
        first_task = asyncio.create_task(
            runtime.handle_platform_chat(group_message("第一条"), platform="test")
        )
        await provider.started.wait()

        second_result, second_turn = await runtime.handle_platform_chat(
            group_message("第二条"),
            platform="test",
        )
        assert second_turn is None
        assert second_result.message is None

        provider.release.set()
        first_result, first_turn = await first_task
        assert first_turn is not None
        assert first_result.message == "过期回复"
        assert provider.calls == 1
        assert await runtime.activate_utterance(first_turn, first_result)

    entries = await client.app.state.audit.list_entries(limit=100)
    assert any(
        entry.action == "turn.scheduled"
        and entry.outcome == "suppress"
        and "utterance_in_flight" in entry.details["reasons"]
        for entry in entries
    )


def _message(conversation_id: str, text: str, *, source_type: str = "direct_message") -> dict:
    return {
        "content": text,
        "source_type": source_type,
        "source_identity": "member-1",
        "conversation_id": conversation_id,
        "authenticated": True,
    }


def test_reply_scheduler_accumulates_group_pressure_and_triggers_once(
    settings: Settings,
) -> None:
    configured = settings.model_copy(
        update={
            "social_group_auto_participation": True,
            "social_group_min_user_turns": 3,
            "social_group_cooldown_seconds": 60.0,
        }
    )
    with TestClient(create_app(configured)) as client:
        payloads = [
            client.post(
                "/v1/chat",
                json=_message("group-pressure", f"消息 {index}", source_type="group_message"),
            ).json()
            for index in range(3)
        ]
        state = asyncio.run(client.app.state.social_state_repository.get("group-pressure"))

    assert [payload["schedule"]["action"] for payload in payloads] == [
        "wait",
        "wait",
        "trigger",
    ]
    assert payloads[-1]["schedule"]["pending_event_ids"] == [
        payload["event"]["event_id"] for payload in payloads
    ]
    assert state is not None
    assert state.pending_event_ids == []
    assert state.is_focused


def test_focus_switches_between_conversations(settings: Settings) -> None:
    with TestClient(create_app(settings)) as client:
        client.post("/v1/chat", json=_message("direct-a", "你好"))
        client.post("/v1/chat", json=_message("direct-b", "你好"))
        first = asyncio.run(client.app.state.social_state_repository.get("direct-a"))
        second = asyncio.run(client.app.state.social_state_repository.get("direct-b"))

    assert first is not None and not first.is_focused
    assert second is not None and second.is_focused


def test_mid_term_impression_and_grounded_attention_cue_enter_context(
    settings: Settings,
) -> None:
    provider = RecordingProvider()
    configured = settings.model_copy(update={"social_mid_term_min_events": 3})
    with TestClient(create_app(configured, llm_provider=provider)) as client:
        client.post("/v1/chat", json=_message("impression-chat", "最近睡眠不太好"))
        response = client.post(
            "/v1/chat",
            json=_message("impression-chat", "睡眠还是有点乱"),
        )
        audit = client.get("/v1/audit", headers={"X-Actor-ID": "owner-1"}).json()
        stored_cue = asyncio.run(
            client.app.state.social_state_repository.latest_cue(
                "impression-chat",
                now=datetime.now(UTC),
                include_used=True,
            )
        )

    assert response.status_code == 200
    reply_context = provider.contexts[-1]
    kinds = {section.kind for section in reply_context.sections}
    assert ContextKind.SESSION_IMPRESSION in kinds
    assert ContextKind.ATTENTION_CUE in kinds
    cue = next(
        section for section in reply_context.sections if section.kind is ContextKind.ATTENTION_CUE
    )
    assert len(cue.source_event_ids) >= 2
    assert stored_cue is not None and stored_cue.used
    impression_audit = next(
        entry for entry in audit if entry["action"] == "session_impression.created"
    )
    assert impression_audit["outcome"] == "deterministic_fallback"


def test_serious_message_does_not_create_attention_drift(settings: Settings) -> None:
    provider = RecordingProvider()
    configured = settings.model_copy(update={"social_mid_term_min_events": 3})
    with TestClient(create_app(configured, llm_provider=provider)) as client:
        client.post("/v1/chat", json=_message("serious-chat", "最近睡眠不太好"))
        client.post("/v1/chat", json=_message("serious-chat", "睡眠让我很焦虑"))

    kinds = {section.kind for section in provider.contexts[-1].sections}
    assert ContextKind.SESSION_IMPRESSION in kinds
    assert ContextKind.ATTENTION_CUE not in kinds


async def test_late_model_result_is_discarded_before_visible_planning(
    settings: Settings,
) -> None:
    provider = BlockingProvider()
    with TestClient(create_app(settings, llm_provider=provider)) as client:
        runtime = client.app.state.runtime
        envelope = IngressEnvelope(
            content="第一条消息",
            source_type=SourceType.DIRECT_MESSAGE,
            source_identity="member-1",
            conversation_id="stale-planning",
            authenticated=True,
        )
        first_turn = await runtime.begin_utterance_turn(
            envelope.conversation_id,
            platform="test",
        )
        assert first_turn is not None
        pending = asyncio.create_task(runtime.handle_chat(envelope, planning_turn=first_turn))
        await provider.started.wait()
        await runtime.begin_utterance_turn("stale-planning", platform="test")
        provider.release.set()
        result = await pending
        entries = await client.app.state.audit.list_entries(limit=50)

    assert result.message is None
    assert result.messages == []
    assert any(entry.action == "model.result_discarded" for entry in entries)
