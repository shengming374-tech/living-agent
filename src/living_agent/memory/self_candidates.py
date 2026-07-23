"""Deterministic, review-only candidates derived from delivered agent speech."""

from __future__ import annotations

import hashlib
import re
from uuid import NAMESPACE_URL, uuid5

from living_agent.models.events import AuthorityLevel, SourceType, TrustedEvent, TrustLevel
from living_agent.models.memory import MemoryCandidateCreate, MemoryFactuality, MemoryType

_UNSAFE_CONTENT = re.compile(
    r"(?:api[_ -]?key|password|token|secret|\u5bc6\u7801|\u4ee4\u724c|\u5bc6\u94a5|"
    r"system\s+(?:prompt|policy)|security\s+policy|\u7cfb\u7edf\u63d0\u793a\u8bcd|\u5b89\u5168\u7b56\u7565)|"
    r"(?:(?:install|enable|authorize|\u5b89\u88c5|\u542f\u7528|\u6388\u6743)"
    r".{0,16}(?:plugin|\u63d2\u4ef6))",
    re.IGNORECASE,
)
_LOW_INFORMATION = re.compile(
    r"^(?:ok(?:ay)?|sure|thanks?|got it|"
    r"\u597d(?:\u7684|\u5440|\u554a)?|\u884c|\u55ef|\u77e5\u9053\u4e86|\u6536\u5230)"
    r"[!\uff01.\u3002]?$",
    re.IGNORECASE,
)


class SelfMemoryCandidateGenerator:
    """Occasionally turn a visible self-expression into an owner-reviewed candidate."""

    def __init__(self, *, enabled: bool, rate: float) -> None:
        if not 0.0 <= rate <= 1.0:
            raise ValueError("self-memory candidate rate must be between 0 and 1")
        self._enabled = enabled
        self._rate = rate

    def generate(self, event: TrustedEvent) -> MemoryCandidateCreate | None:
        if not self._eligible_event(event) or not self._selected(event.event_id):
            return None
        assert isinstance(event.content, dict)
        raw_text = event.content.get("text")
        if not isinstance(raw_text, str):
            return None
        text = " ".join(raw_text.strip().split())
        if (
            len(text) < 8
            or len(text) > 800
            or _LOW_INFORMATION.fullmatch(text) is not None
            or _UNSAFE_CONTENT.search(text) is not None
        ):
            return None
        subject_excerpt = text.rstrip("\u3002.\uff01!")[:48].strip()
        return MemoryCandidateCreate(
            candidate_id=str(
                uuid5(NAMESPACE_URL, f"living-agent:self-memory:{event.event_id}")
            ),
            type=MemoryType.SELF,
            content=text,
            subject=f"\u81ea\u53d1\u8bb0\u5fc6:{subject_excerpt}",
            source_event_ids=[event.event_id],
            factuality=MemoryFactuality.INFERRED,
            confidence=0.55,
            importance=0.35,
            scope=f"conversation:{event.conversation_id}",
        )

    def _eligible_event(self, event: TrustedEvent) -> bool:
        if (
            not self._enabled
            or self._rate == 0.0
            or event.source_type is not SourceType.AGENT_MESSAGE
            or event.source_identity != "living-agent"
            or event.trust_level is not TrustLevel.TRUSTED
            or event.authority_level is not AuthorityLevel.SYSTEM
            or event.conversation_id is None
            or not isinstance(event.content, dict)
        ):
            return False
        return (
            event.content.get("unit_index") == 0
            and event.content.get("speech_function") == "reaction"
        )

    def _selected(self, event_id: str) -> bool:
        digest = hashlib.sha256(f"self-memory:{event_id}".encode()).digest()
        sample = int.from_bytes(digest[:8], "big") / 2**64
        return sample < self._rate
