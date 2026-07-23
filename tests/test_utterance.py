import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from living_agent.cognition.social import SocialCognition
from living_agent.config import Settings
from living_agent.interaction.turn_gate import TurnGate
from living_agent.interaction.utterance import UtteranceCoordinator
from living_agent.models.conversation import ChatResult, SpeechUnit, TurnDecision, UtteranceSession
from living_agent.models.events import AuthorityLevel, SourceType, TrustedEvent, TrustLevel


def decision(mode: str, minimum: int, maximum: int) -> TurnDecision:
    return TurnDecision(
        mode=mode,  # type: ignore[arg-type]
        urgency=0.6,
        expected_units_min=minimum,
        expected_units_max=maximum,
        interruption_tolerance=0.8,
        target_event_ids=["event-1"],
        reason_code="test",
    )


def test_react_keeps_only_one_short_social_unit() -> None:
    session = SocialCognition(TurnGate()).plan_utterance(
        "嘿嘿, 被你发现啦!\n我刚好就在这里。",
        decision("react", 1, 1),
    )

    assert [unit.text for unit in session.units] == ["嘿嘿, 被你发现啦!"]
    assert session.units[0].delay_min_ms == 0
    assert session.units[0].cancellable is False


def test_engage_preserves_two_or_three_semantic_lines_as_short_units() -> None:
    session = SocialCognition(TurnGate()).plan_utterance(
        "哇, 这个点子一下就亮起来了!\n先别急着把它讲完整。\n我想听听最开始那一下是怎么冒出来的?",
        decision("engage", 2, 3),
    )

    assert [unit.text for unit in session.units] == [
        "哇, 这个点子一下就亮起来了!",
        "先别急着把它讲完整。",
        "我想听听最开始那一下是怎么冒出来的?",
    ]
    assert all(unit.cancellable for unit in session.units[1:])
    assert all(unit.delay_min_ms == 300 for unit in session.units[1:])


def test_verified_task_result_uses_task_speech_function() -> None:
    session = SocialCognition(TurnGate()).plan_utterance(
        "我核对过了\uff1a1 + 1 = 2",
        decision("act", 1, 1),
    )

    assert session.units[0].function == "task_result"


def test_configured_style_removes_sentence_full_stops_but_preserves_decimals() -> None:
    session = SocialCognition(TurnGate(), avoid_full_stops=True).plan_utterance(
        "完成了。版本是 0.2.0. 下一步继续!",
        decision("engage", 2, 3),
    )

    assert [unit.text for unit in session.units] == ["完成了", "版本是 0.2.0 下一步继续!"]


def test_followup_delay_is_configurable_and_validated() -> None:
    session = SocialCognition(
        TurnGate(),
        followup_delay_min_ms=120,
        followup_delay_max_ms=280,
    ).plan_utterance("第一条\n第二条", decision("engage", 2, 2))

    assert [(unit.delay_min_ms, unit.delay_max_ms) for unit in session.units] == [
        (0, 0),
        (120, 280),
    ]
    with pytest.raises(ValidationError, match="delay_min_ms cannot exceed"):
        SpeechUnit(
            function="continuation",
            text="invalid",
            delay_min_ms=500,
            delay_max_ms=100,
            cancellable=True,
        )
    with pytest.raises(ValidationError, match="social_followup_delay_min_ms"):
        Settings(
            social_followup_delay_min_ms=700,
            social_followup_delay_max_ms=600,
        )


def utterance_result(*texts: str, delay_ms: int = 5000) -> ChatResult:
    turn = decision("engage", 2, len(texts))
    session = UtteranceSession(
        intention="test",
        units=[
            SpeechUnit(
                function="reaction" if index == 0 else "continuation",
                text=text,
                delay_min_ms=0 if index == 0 else delay_ms,
                delay_max_ms=0 if index == 0 else delay_ms,
                cancellable=index > 0,
            )
            for index, text in enumerate(texts)
        ],
        interruption_policy="cancel_unsent_on_new_message",
    )
    return ChatResult(
        event=TrustedEvent(
            event_type="message.received",
            content="test",
            source_type=SourceType.DIRECT_MESSAGE,
            source_identity="member-1",
            conversation_id="conversation-1",
            trust_level=TrustLevel.AUTHENTICATED,
            authority_level=AuthorityLevel.MEMBER,
        ),
        turn=turn,
        message=texts[0],
        messages=list(texts),
        utterance=session,
    )


async def test_new_turn_cancels_wait_and_replans_remaining_units(
    client: TestClient,
) -> None:
    coordinator = UtteranceCoordinator(audit=client.app.state.audit, delays_enabled=True)
    old_result = utterance_result("old first", "old continuation")
    old_turn = await coordinator.begin_turn("conversation-1", platform="test")
    assert await coordinator.activate(old_turn, old_result)
    assert await coordinator.wait_until_ready(old_turn, old_result, unit_index=0)
    assert await coordinator.mark_started(old_turn, old_result, unit_index=0)

    waiting = asyncio.create_task(coordinator.wait_until_ready(old_turn, old_result, unit_index=1))
    await asyncio.sleep(0)
    new_turn = await coordinator.begin_turn("conversation-1", platform="test")

    assert await waiting is False
    assert old_result.utterance is not None
    assert old_result.utterance.state == "cancelled"
    assert new_turn.replaced_session_id == old_result.utterance.session_id

    new_result = utterance_result("new first", "new continuation")
    assert await coordinator.activate(new_turn, new_result)
    entries = await client.app.state.audit.list_entries(limit=20)
    interruption = next(entry for entry in entries if entry.action == "utterance.interrupted")
    replanned = next(entry for entry in entries if entry.action == "utterance.replanned")
    assert interruption.details["sent_count"] == 1
    assert interruption.details["unsent_count"] == 1
    assert replanned.details["replaced_session_id"] == old_result.utterance.session_id
    assert replanned.details["utterance_session_id"] == new_result.utterance.session_id


async def test_test_mode_disables_real_waits(client: TestClient) -> None:
    coordinator = UtteranceCoordinator(audit=client.app.state.audit, delays_enabled=False)
    result = utterance_result("first", "second", delay_ms=10000)
    turn = await coordinator.begin_turn("conversation-1", platform="test")
    assert await coordinator.activate(turn, result)
    assert await coordinator.wait_until_ready(turn, result, unit_index=0)
    assert await coordinator.mark_started(turn, result, unit_index=0)

    assert coordinator.delay_ms(result.utterance.units[1]) == 0
    assert await coordinator.wait_until_ready(turn, result, unit_index=1)
