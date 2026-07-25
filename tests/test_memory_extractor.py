from __future__ import annotations

import pytest

from living_agent.memory.extractor import MemoryCandidateExtractor
from living_agent.models.events import (
    AuthorityLevel,
    SourceType,
    TrustedEvent,
    TrustLevel,
)


def _event(content: str) -> TrustedEvent:
    return TrustedEvent(
        event_type="message.received",
        content=content,
        source_type=SourceType.DIRECT_MESSAGE,
        source_identity="member-1",
        conversation_id="memory-extractor",
        trust_level=TrustLevel.AUTHENTICATED,
        authority_level=AuthorityLevel.MEMBER,
    )


@pytest.mark.parametrize(
    "content",
    [
        "我叫什么",
        "我是谁",
        "我喜欢什么",
        "我住哪里",
        "我叫盛茗吗",
        "我喜欢茉莉花茶的话就每天喝",
        "我叫盛茗只是举个例子",
    ],
)
def test_unpunctuated_questions_and_hypotheticals_are_not_candidates(
    content: str,
) -> None:
    extractor = MemoryCandidateExtractor(enabled=True)

    assert extractor.extract_all(_event(content)) == []


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("我叫盛茗", "我叫盛茗"),
        ("我喜欢茉莉花茶", "我喜欢茉莉花茶"),
    ],
)
def test_assertive_self_claims_remain_candidates(content: str, expected: str) -> None:
    extractor = MemoryCandidateExtractor(enabled=True)

    candidates = extractor.extract_all(_event(content))

    assert [candidate.content for candidate in candidates] == [expected]
