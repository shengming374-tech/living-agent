from datetime import UTC, datetime, timedelta

from living_agent.interaction.momentum import ConversationMomentum
from living_agent.interaction.turn_gate import TurnGate
from living_agent.models.events import (
    AuthorityLevel,
    SourceType,
    TrustedEvent,
    TrustLevel,
)

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def event(
    content: str | dict[str, object],
    source_type: SourceType,
    *,
    created_at: datetime = NOW,
) -> TrustedEvent:
    return TrustedEvent(
        event_type="message.received",
        content=content,
        source_type=source_type,
        source_identity="living-agent" if source_type is SourceType.AGENT_MESSAGE else "user-1",
        conversation_id="conversation-1",
        trust_level=(
            TrustLevel.TRUSTED
            if source_type is SourceType.AGENT_MESSAGE
            else TrustLevel.AUTHENTICATED
        ),
        authority_level=(
            AuthorityLevel.SYSTEM
            if source_type is SourceType.AGENT_MESSAGE
            else AuthorityLevel.MEMBER
        ),
        created_at=created_at,
    )


def test_momentum_tracks_recent_back_and_forth_and_agent_unit_count() -> None:
    history = [
        event("我有个点子", SourceType.DIRECT_MESSAGE, created_at=NOW - timedelta(minutes=2)),
        event("听起来很有意思。\n继续说呀。", SourceType.AGENT_MESSAGE),
    ]

    momentum = ConversationMomentum.from_history(history, now=NOW)

    assert momentum.phase == "back_and_forth"
    assert momentum.agent_spoke_last is True
    assert momentum.user_turns_since_agent == 0
    assert momentum.recent_agent_unit_count == 2


def test_momentum_expires_old_conversation_activity() -> None:
    history = [
        event("很久以前的消息", SourceType.DIRECT_MESSAGE, created_at=NOW - timedelta(hours=1))
    ]

    momentum = ConversationMomentum.from_history(history, now=NOW)

    assert momentum.phase == "new"
    assert momentum.recent_turn_count == 0


def test_momentum_groups_individually_delivered_units_by_session() -> None:
    history = [
        event(
            {"text": f"第{index}条", "utterance_session_id": "session-1"},
            SourceType.AGENT_MESSAGE,
        )
        for index in range(1, 4)
    ]

    momentum = ConversationMomentum.from_history(history, now=NOW)

    assert momentum.recent_agent_unit_count == 3


def test_turn_gate_keeps_acknowledgement_short_even_during_user_run() -> None:
    momentum = ConversationMomentum(
        phase="user_run",
        recent_turn_count=1,
        agent_spoke_last=False,
        user_turns_since_agent=1,
        recent_agent_unit_count=0,
    )

    decision = TurnGate().decide(event("好", SourceType.DIRECT_MESSAGE), momentum)

    assert decision.mode == "react"
    assert decision.expected_units_max == 1
    assert decision.reason_code == "brief_acknowledgement"


def test_turn_gate_engages_with_short_question_or_continued_thought() -> None:
    new = ConversationMomentum(
        phase="new",
        recent_turn_count=0,
        agent_spoke_last=False,
        user_turns_since_agent=0,
        recent_agent_unit_count=0,
    )
    user_run = new.model_copy(
        update={"phase": "user_run", "recent_turn_count": 1, "user_turns_since_agent": 1}
    )

    question = TurnGate().decide(event("你觉得呢\uff1f", SourceType.DIRECT_MESSAGE), new)
    continuation = TurnGate().decide(event("还有这个", SourceType.DIRECT_MESSAGE), user_run)

    assert question.mode == "engage"
    assert question.reason_code == "direct_question"
    assert continuation.mode == "engage"
    assert continuation.reason_code == "continued_user_thought"
