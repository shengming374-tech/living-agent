from living_agent.cognition.social import SocialCognition
from living_agent.interaction.turn_gate import TurnGate
from living_agent.models.conversation import TurnDecision


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
