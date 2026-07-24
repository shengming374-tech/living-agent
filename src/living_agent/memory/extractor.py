"""Conservative deterministic extraction of pending memory candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from living_agent.models.events import SourceType, TrustedEvent, TrustLevel
from living_agent.models.memory import MemoryCandidateCreate, MemoryFactuality, MemoryType
from living_agent.trust.taint import TaintLabel


@dataclass(frozen=True)
class _ClaimPattern:
    category: str
    pattern: re.Pattern[str]
    memory_type: MemoryType = MemoryType.SEMANTIC
    importance: float = 0.5


_CLAIM_PATTERNS: tuple[_ClaimPattern, ...] = (
    _ClaimPattern(
        "profile:occupation",
        re.compile(
            r"^(?:我(?:是(?:一名|一个)|做)|我的(?:职业|工作)是|我从事)(?P<detail>.{1,80})$"
        ),
        importance=0.65,
    ),
    _ClaimPattern(
        "profile:name",
        re.compile(r"^(?:我叫|我的(?:名字|昵称)是|我是)(?P<detail>.{1,80})$"),
        importance=0.7,
    ),
    _ClaimPattern(
        "profile:age",
        re.compile(r"^(?:我(?:今年)?|我的年龄是)(?P<detail>\d{1,3}\s*岁)$"),
        importance=0.6,
    ),
    _ClaimPattern(
        "profile:birthday",
        re.compile(r"^(?:我的生日是|我(?:出生于|出生在))(?P<detail>.{1,80})$"),
        importance=0.65,
    ),
    _ClaimPattern(
        "profile:location",
        re.compile(r"^(?:我(?:住在|来自|居住在)|我的家在)(?P<detail>.{1,120})$"),
        importance=0.6,
    ),
    _ClaimPattern(
        "relationship:pet",
        re.compile(
            r"^(?:我(?:养了?|有)(?P<detail>.{1,120}(?:猫|狗|兔|鸟|宠物).{0,80})|"
            r"我的(?P<pet_kind>猫|狗|兔|鸟|宠物)(?:叫|名字是)(?P<pet_name>.{1,80}))$"
        ),
        memory_type=MemoryType.RELATIONSHIP,
        importance=0.65,
    ),
    _ClaimPattern(
        "relationship:family",
        re.compile(
            r"^我的(?P<relation>爸爸|父亲|妈妈|母亲|哥哥|姐姐|弟弟|妹妹|丈夫|妻子|"
            r"伴侣|爱人|儿子|女儿)(?:叫|名字是|是)(?P<detail>.{1,100})$"
        ),
        memory_type=MemoryType.RELATIONSHIP,
        importance=0.65,
    ),
    _ClaimPattern(
        "preference",
        re.compile(r"^(?:我|咱)(?:最)?(?:喜欢|偏好|不喜欢|讨厌|爱)(?P<detail>.{1,240})$"),
    ),
    _ClaimPattern(
        "schedule",
        re.compile(
            r"^(?:我(?:每(?:天|周|星期|月|年).{1,180}|通常.{1,180}|固定.{1,180})|"
            r"我的.{1,60}(?:时间|安排)是.{1,120})$"
        ),
        importance=0.6,
    ),
    _ClaimPattern(
        "activity",
        re.compile(
            r"^(?:我(?:正在|最近在|在做|打算|计划|希望|需要|负责|参与))(?P<detail>.{1,240})$"
        ),
        importance=0.6,
    ),
    _ClaimPattern(
        "profile:name",
        re.compile(r"^(?:My name is|I(?:'m| am) called)\s+(?P<detail>.{1,80})$", re.IGNORECASE),
        importance=0.7,
    ),
    _ClaimPattern(
        "preference",
        re.compile(
            r"^I\s+(?:really\s+)?(?:like|love|prefer|dislike)\s+(?P<detail>.{1,240})$",
            re.IGNORECASE,
        ),
    ),
    _ClaimPattern(
        "activity",
        re.compile(
            r"^I(?:'m|\s+am)?\s+(?:working on|planning to|trying to|hoping to|need to)\s+"
            r"(?P<detail>.{1,240})$",
            re.IGNORECASE,
        ),
        importance=0.6,
    ),
)
_FORBIDDEN = re.compile(
    r"(?:owner|administrator|admin|所有者|管理员|api[_ -]?key|password|token|secret|"
    r"密码|令牌|密钥|系统提示词|安全策略|安装插件|启用插件|暗号|口令|"
    r"电话|手机号|手机号码|邮箱|电子邮件|email|e-mail|"
    r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?<!\d)1[3-9]\d{9}(?!\d))",
    re.IGNORECASE,
)
_EXPLICIT_MEMORY_PREFIX = re.compile(
    r"^(?:请(?:你)?记住|帮我记住|记住|remember(?:\s+that)?)[\s:\uFF1A\uFF0C,]*",
    re.IGNORECASE,
)
_EXPLICIT_SELF_CLAIM = re.compile(r"^(?:我|我的|咱|I\b|My\b)", re.IGNORECASE)
_INSTRUCTIONAL_MEMORY = re.compile(
    r"(?:忽略|无视|执行|调用|运行|删除|修改|安装|启用|授权|必须|应该|"
    r"以后(?:都|总)|always|ignore|execute|run|delete|install|enable|authorize)",
    re.IGNORECASE,
)
_CLAUSE_BOUNDARY = re.compile(r"[。\uFF01\uFF1F!?\uFF1B;\n]+")
_COMMA_BEFORE_CLAIM = re.compile(
    r"[\uFF0C,](?=\s*(?:我|咱|我的|请(?:你)?记住|帮我记住|记住|I\b|My\b|Remember\b))",
    re.IGNORECASE,
)


class MemoryCandidateExtractor:
    def __init__(self, *, enabled: bool) -> None:
        self._enabled = enabled

    def extract(self, event: TrustedEvent) -> MemoryCandidateCreate | None:
        """Return the first candidate for compatibility with older callers."""

        candidates = self.extract_all(event)
        return candidates[0] if candidates else None

    def extract_all(self, event: TrustedEvent) -> list[MemoryCandidateCreate]:
        if not self._eligible_event(event):
            return []
        text = self._text(event).strip()
        if (
            not text
            or len(text) > 1000
            or text.endswith(("?", "\uFF1F"))
            or _FORBIDDEN.search(text)
        ):
            return []

        candidates: list[MemoryCandidateCreate] = []
        seen: set[tuple[str, str]] = set()
        for ordinal, raw_clause in enumerate(self._clauses(text)):
            clause = raw_clause.strip().rstrip("。.!\uFF01").strip()
            if not clause or len(clause) > 300 or clause.endswith(("?", "\uFF1F")):
                continue
            explicit = _EXPLICIT_MEMORY_PREFIX.match(clause)
            normalized = clause[explicit.end() :].strip() if explicit is not None else clause
            normalized = normalized.rstrip("。.!\uFF01").strip()
            if (
                not normalized
                or normalized.endswith(("?", "\uFF1F"))
                or _FORBIDDEN.search(normalized)
                or (explicit is not None and _INSTRUCTIONAL_MEMORY.search(normalized))
            ):
                continue

            matched = self._match_claim(normalized)
            if matched is None and (
                explicit is None or _EXPLICIT_SELF_CLAIM.match(normalized) is None
            ):
                continue
            pattern, match = matched if matched is not None else (None, None)
            category = pattern.category if pattern is not None else "explicit"
            memory_type = pattern.memory_type if pattern is not None else MemoryType.SEMANTIC
            importance = pattern.importance if pattern is not None else 0.6
            dedupe_key = (category, normalized.casefold())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            candidates.append(
                self._candidate(
                    event,
                    content=normalized,
                    category=category,
                    ordinal=ordinal,
                    memory_type=memory_type,
                    importance=importance,
                    subject_detail=self._subject_detail(match, normalized),
                )
            )
        return candidates

    @staticmethod
    def _match_claim(clause: str) -> tuple[_ClaimPattern, re.Match[str]] | None:
        for pattern in _CLAIM_PATTERNS:
            match = pattern.pattern.fullmatch(clause)
            if match is not None:
                return pattern, match
        return None

    @staticmethod
    def _subject_detail(match: re.Match[str] | None, fallback: str) -> str:
        if match is None:
            return " ".join(fallback.split())[:80]
        values = match.groupdict()
        detail = next(
            (
                values[key]
                for key in ("pet_name", "relation", "detail")
                if values.get(key)
            ),
            fallback,
        )
        return " ".join(detail.split())[:80]

    @staticmethod
    def _candidate(
        event: TrustedEvent,
        *,
        content: str,
        category: str,
        ordinal: int,
        memory_type: MemoryType,
        importance: float,
        subject_detail: str,
    ) -> MemoryCandidateCreate:
        stable_key = f"{event.event_id}:{ordinal}:{category}:{content.casefold()}"
        subject = f"{event.source_identity} 自述:{category}"
        if category not in {
            "profile:name",
            "profile:age",
            "profile:birthday",
            "profile:location",
            "profile:occupation",
        }:
            subject = f"{subject}:{subject_detail}"
        return MemoryCandidateCreate(
            candidate_id=str(uuid5(NAMESPACE_URL, f"living-agent:auto-memory:{stable_key}")),
            type=memory_type,
            content=content,
            subject=subject,
            source_event_ids=[event.event_id],
            factuality=MemoryFactuality.REPORTED,
            confidence=0.72 if category != "explicit" else 0.8,
            importance=importance,
            scope=MemoryCandidateExtractor._scope(event),
        )

    @staticmethod
    def _clauses(text: str) -> list[str]:
        sentences = _CLAUSE_BOUNDARY.split(text)
        return [clause for sentence in sentences for clause in _COMMA_BEFORE_CLAIM.split(sentence)]

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
