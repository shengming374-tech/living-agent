"""Conservative deterministic extraction of pending memory candidates."""

from __future__ import annotations

import re
from uuid import NAMESPACE_URL, uuid5

from living_agent.models.events import SourceType, TrustedEvent, TrustLevel
from living_agent.models.memory import MemoryCandidateCreate, MemoryFactuality, MemoryType
from living_agent.trust.taint import TaintLabel

_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "preference",
        re.compile(
            r"^(?:我|咱)(?:最)?(?:喜欢|偏好|不喜欢|讨厌|爱)(?P<detail>.{1,240})$"
        ),
    ),
    (
        "profile",
        re.compile(
            r"^(?:我叫|我的(?:名字|昵称)是|我是)(?P<detail>.{1,160})$"
        ),
    ),
    (
        "activity",
        re.compile(
            r"^(?:我(?:正在|最近在|打算|计划|希望|需要))(?P<detail>.{1,240})$"
        ),
    ),
    (
        "preference",
        re.compile(
            r"^I\s+(?:really\s+)?(?:like|love|prefer|dislike)\s+(?P<detail>.{1,240})$",
            re.IGNORECASE,
        ),
    ),
    (
        "activity",
        re.compile(
            r"^I(?:'m|\s+am)?\s+(?:working on|planning to|trying to|hoping to|need to)\s+"
            r"(?P<detail>.{1,240})$",
            re.IGNORECASE,
        ),
    ),
)
_FORBIDDEN = re.compile(
    r"(?:owner|administrator|admin|所有者|管理员|api[_ -]?key|password|token|secret|"
    r"密码|令牌|密钥|系统提示词|安全策略|安装插件|启用插件|暗号|口令)",
    re.IGNORECASE,
)


class MemoryCandidateExtractor:
    def __init__(self, *, enabled: bool) -> None:
        self._enabled = enabled

    def extract(self, event: TrustedEvent) -> MemoryCandidateCreate | None:
        if not self._eligible_event(event):
            return None
        text = self._text(event).strip()
        if not text or len(text) > 500 or text.endswith(("?", "\uFF1F")):
            return None
        if _FORBIDDEN.search(text):
            return None
        normalized = text.rstrip("。.!\uFF01").strip()
        for category, pattern in _CLAIM_PATTERNS:
            match = pattern.fullmatch(normalized)
            if match is not None:
                detail = " ".join(match.group("detail").split())[:80]
                subject = f"{event.source_identity} 自述:{category}"
                if category != "profile":
                    subject = f"{subject}:{detail}"
                return MemoryCandidateCreate(
                    candidate_id=str(
                        uuid5(
                            NAMESPACE_URL,
                            f"living-agent:auto-memory:{event.event_id}:{category}",
                        )
                    ),
                    type=MemoryType.SEMANTIC,
                    content=normalized,
                    subject=subject,
                    source_event_ids=[event.event_id],
                    factuality=MemoryFactuality.REPORTED,
                    confidence=0.65,
                    importance=0.5,
                    scope=self._scope(event),
                )
        return None

    def _eligible_event(self, event: TrustedEvent) -> bool:
        return (
            self._enabled
            and event.trust_level is TrustLevel.AUTHENTICATED
            and event.source_type in {SourceType.DIRECT_MESSAGE, SourceType.GROUP_MESSAGE}
            and event.source_identity is not None
            and event.conversation_id is not None
            and TaintLabel.SUSPECTED_INSTRUCTION.value not in event.taint_labels
        )

    @staticmethod
    def _text(event: TrustedEvent) -> str:
        if isinstance(event.content, str):
            return event.content
        value = event.content.get("text")
        return value if isinstance(value, str) else ""

    @staticmethod
    def _scope(event: TrustedEvent) -> str:
        if event.source_type is SourceType.DIRECT_MESSAGE:
            return f"private:{event.source_identity}"
        return f"conversation:{event.conversation_id}"
