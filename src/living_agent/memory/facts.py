"""Deterministic parsing and recall routing for small social facts.

This module is deliberately independent from persistence and model providers.  It
turns only explicit self-reports into structured facts and classifies recall
questions before the broader semantic-memory path is considered.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import Literal

FactCardinality = Literal["single", "set"]
PreferenceKind = Literal["like", "dislike"]
FACT_SCHEMA = "social.fact.v1"


class RecallRoute(StrEnum):
    """The narrowest memory family that can answer a query."""

    EXACT_FACT = "exact_fact"
    FACT_SET = "fact_set"
    EPISODIC = "episodic"
    RELATIONSHIP = "relationship"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class FactSpec:
    """One explicit, sourceable social fact extracted from a self-report."""

    key: str
    value: str
    cardinality: FactCardinality
    surface_text: str
    correction: bool = False
    schema: str = field(default=FACT_SCHEMA, init=False)

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("fact key cannot be empty")
        if not self.value.strip():
            raise ValueError("fact value cannot be empty")
        if self.cardinality not in {"single", "set"}:
            raise ValueError("fact cardinality must be single or set")
        if not self.surface_text.strip():
            raise ValueError("fact surface text cannot be empty")

    @property
    def content(self) -> dict[str, str]:
        """Return the stable payload stored by a future persistence adapter."""

        return {
            "schema": self.schema,
            "key": self.key,
            "value": self.value,
            "cardinality": self.cardinality,
            "surface_text": self.surface_text,
        }


@dataclass(frozen=True, slots=True)
class RecallRouteResult:
    """A deterministic recall decision with an optional fact selector."""

    route: RecallRoute
    fact_key: str | None = None
    cardinality: FactCardinality | None = None
    reason_code: str = "no_memory_intent"


@dataclass(frozen=True, slots=True)
class _FactPattern:
    key: str
    expression: re.Pattern[str]
    correction: bool = False


_TRAILING_SENTENCE_MARKS = re.compile(r"[\s。.!！]+$")
_QUESTION_WORDS = re.compile(
    r"(?:什么|谁|哪(?:个|些|里|儿)?|多少|几(?:岁|号|点)?|怎么|如何|是否|吗|嘛|么)"
)
_ENGLISH_QUESTION = re.compile(
    r"^(?:what|who|where|when|why|how|which|do|does|did|is|are|am|"
    r"can|could|would|should|will|have|has)\b",
    re.IGNORECASE,
)

_SINGLE_FACT_PATTERNS: tuple[_FactPattern, ...] = (
    # Explicit name corrections are intentionally separate from ordinary
    # self-reports.  A later contradictory "我叫..." remains a normal claim
    # and therefore still requires conflict review by the persistence layer.
    _FactPattern(
        "profile.name",
        re.compile(
            r"^(?:我)?(?:现在叫|改成|改名(?:为|叫)|名字(?:现在)?改成)"
            r"\s*(?P<value>.{1,80}?)(?:了)?$"
        ),
        correction=True,
    ),
    _FactPattern(
        "profile.name",
        re.compile(
            r"^(?:我)?以前叫.{1,80}?[,，]\s*(?:我)?现在叫\s*(?P<value>.{1,80})$"
        ),
        correction=True,
    ),
    _FactPattern(
        "profile.name",
        re.compile(
            r"^(?:我)?(?:不叫|不是).{1,80}?[,，]\s*(?:而是|是|(?:我)?叫)"
            r"\s*(?P<value>.{1,80})$"
        ),
        correction=True,
    ),
    _FactPattern(
        "profile.name",
        re.compile(
            r"^(?:my name is now|i am now called|i'm now called|now call me)\s+"
            r"(?P<value>.{1,80})$",
            re.IGNORECASE,
        ),
        correction=True,
    ),
    _FactPattern(
        "profile.name",
        re.compile(
            r"^call me\s+(?P<value>.{1,80}?)\s+instead$",
            re.IGNORECASE,
        ),
        correction=True,
    ),
    _FactPattern(
        "profile.name",
        re.compile(
            r"^(?:my name is|i am|i'm)\s+not\s+.{1,80}?\s+but\s+"
            r"(?:(?:my name is|i am|i'm)\s+)?(?P<value>.{1,80})$",
            re.IGNORECASE,
        ),
        correction=True,
    ),
    _FactPattern(
        "profile.name",
        re.compile(
            r"^i used to be called .{1,80}?[,;]\s*"
            r"(?:now\s+)?(?:call me|i am called|i'm called)\s+"
            r"(?P<value>.{1,80})$",
            re.IGNORECASE,
        ),
        correction=True,
    ),
    _FactPattern(
        "profile.nickname",
        re.compile(r"^我的(?:昵称|外号)是\s*(?P<value>.{1,80})$"),
    ),
    _FactPattern(
        "profile.nickname",
        re.compile(r"^(?:你可以|大家都)?叫我\s*(?P<value>.{1,80})$"),
    ),
    _FactPattern(
        "profile.nickname",
        re.compile(
            r"^(?:my nickname is|you can call me)\s+(?P<value>.{1,80})$",
            re.IGNORECASE,
        ),
    ),
    _FactPattern(
        "profile.name",
        re.compile(r"^(?:我叫|我的名字是)\s*(?P<value>.{1,80})$"),
    ),
    _FactPattern(
        "profile.name",
        re.compile(
            r"^(?:my name is|i am called|i'm called)\s+(?P<value>.{1,80})$",
            re.IGNORECASE,
        ),
    ),
    _FactPattern(
        "profile.birthday",
        re.compile(r"^我的生日是\s*(?P<value>.{1,80})$"),
    ),
    _FactPattern(
        "profile.birthday",
        re.compile(
            r"^我出生于\s*(?P<value>[^,，]{0,40}(?:\d|年|月|日|号)[^,，]{0,40})$"
        ),
    ),
    _FactPattern(
        "profile.birthday",
        re.compile(
            r"^(?:my birthday is|i was born on)\s+(?P<value>.{1,80})$",
            re.IGNORECASE,
        ),
    ),
    _FactPattern(
        "profile.location",
        re.compile(r"^(?:我住在|我居住在|我来自|我的家在)\s*(?P<value>.{1,120})$"),
    ),
    _FactPattern(
        "profile.location",
        re.compile(r"^我出生在\s*(?P<value>.{1,120})$"),
    ),
    _FactPattern(
        "profile.location",
        re.compile(
            r"^(?:i live in|i live at|i am from|i'm from|my home is in)\s+"
            r"(?P<value>.{1,120})$",
            re.IGNORECASE,
        ),
    ),
    _FactPattern(
        "profile.occupation",
        re.compile(r"^(?:我的职业是|我的工作是|我从事)\s*(?P<value>.{1,120})$"),
    ),
    _FactPattern(
        "profile.occupation",
        re.compile(
            r"^(?:my occupation is|i work as)\s+(?P<value>.{1,120})$",
            re.IGNORECASE,
        ),
    ),
)

_PREFERENCE_PATTERNS: tuple[tuple[PreferenceKind, re.Pattern[str]], ...] = (
    (
        "like",
        re.compile(r"^(?:我|咱)(?:最)?(?:喜欢|喜爱|爱|偏好)\s*(?P<value>.{1,240})$"),
    ),
    (
        "dislike",
        re.compile(r"^(?:我|咱)(?:不喜欢|讨厌|厌恶)\s*(?P<value>.{1,240})$"),
    ),
    (
        "like",
        re.compile(
            r"^i\s+(?:really\s+)?(?:like|love|prefer)\s+(?P<value>.{1,240})$",
            re.IGNORECASE,
        ),
    ),
    (
        "dislike",
        re.compile(
            r"^i\s+(?:really\s+)?(?:dislike|hate)\s+(?P<value>.{1,240})$",
            re.IGNORECASE,
        ),
    ),
)

_NAME_RECALL = (
    re.compile(r"^(?:你(?:还)?记得)?我叫什么(?:吗)?$"),
    re.compile(r"^(?:你(?:还)?记得)?我的名字(?:是|叫)?什么(?:吗)?$"),
    re.compile(r"^(?:你知道)?我是谁(?:吗)?$"),
    re.compile(
        r"^(?:what is|what's) my name$|^who am i$|^do you remember my name$",
        re.IGNORECASE,
    ),
)
_LIKE_RECALL = re.compile(
    r"(?:我(?:最)?喜欢什么|我的(?:喜好|偏好)(?:是什么|有哪些)?|"
    r"what do i (?:like|love|prefer)|what are my likes)",
    re.IGNORECASE,
)
_DISLIKE_RECALL = re.compile(
    r"(?:我(?:不喜欢|讨厌)什么|我有哪些不喜欢的|"
    r"what do i (?:dislike|hate)|what are my dislikes)",
    re.IGNORECASE,
)
_TOOL_OR_FILE_QUERY = re.compile(
    r"(?:调用.{0,20}(?:工具|shell|终端|命令)|(?:工具|shell|终端|命令).{0,20}(?:调用|运行|执行)|"
    r"桌面(?:上|里|文件)|文件夹|目录|浏览器|网页|"
    r"\b(?:use|run|call|open)\b.{0,30}\b(?:tool|shell|terminal|command|file|folder|desktop)\b|"
    r"\b(?:tool|shell|terminal|command|desktop files?)\b)",
    re.IGNORECASE,
)
_RELATIONSHIP_RECALL = re.compile(
    r"(?:我的(?:爸爸|父亲|妈妈|母亲|哥哥|姐姐|弟弟|妹妹|丈夫|妻子|伴侣|爱人|"
    r"儿子|女儿|猫|狗|兔|鸟|宠物).{0,40}(?:谁|什么|叫|名字)|"
    r"(?:我(?:的)?|家里(?:的)?)?(?:猫|狗|兔|鸟|宠物|小动物)"
    r".{0,40}(?:叫什么|名字|是谁)|"
    r"我和.{1,80}(?:是什么关系|关系如何)|"
    r"\bwho is my (?:father|mother|brother|sister|husband|wife|partner|son|daughter)\b|"
    r"\bwhat(?:'s| is) my (?:cat|dog|pet)(?:'s)? name\b|"
    r"\bwhat is my relationship with\b)",
    re.IGNORECASE,
)
_EPISODIC_RECALL = re.compile(
    r"(?:还记得(?:那次|上次|之前)|回忆(?:一下)?(?:那次|上次|之前)|"
    r"(?:上次|之前|那天).{0,40}(?:发生了什么|做了什么|聊了什么)|"
    r"我们.{0,30}(?:经历过|发生过).{0,30}什么|"
    r"我(?:什么时候|哪天|几点).{0,40}(?:上课|工作|开会|出发|回来|安排)|"
    r"我的(?:日程|安排|计划).{0,40}(?:什么|怎样|怎么|什么时候)|"
    r"\bremember when\b|\bwhat happened (?:last time|before|that day)\b|"
    r"\bwhat did we (?:do|discuss|talk about) (?:last time|before)\b)",
    re.IGNORECASE,
)
_FORGET_FACT = re.compile(
    r"^(?:请)?(?:忘记|忘掉|删除|不要再记得|别再记得)(?:关于)?我(?:的)?"
    r"(?P<field>名字|姓名|昵称|外号|生日|出生日期|住址|住在哪里|所在地|职业|工作)"
    r"(?:这条)?(?:事实|记忆)?$"
)
_FORGET_KEYS = {
    "名字": "profile.name",
    "姓名": "profile.name",
    "昵称": "profile.nickname",
    "外号": "profile.nickname",
    "生日": "profile.birthday",
    "出生日期": "profile.birthday",
    "住址": "profile.location",
    "住在哪里": "profile.location",
    "所在地": "profile.location",
    "职业": "profile.occupation",
    "工作": "profile.occupation",
}


def extract_fact(text: str) -> FactSpec | None:
    """Extract one conservative fact from an explicit self-report.

    Questions are rejected before statement patterns are evaluated, including
    punctuation-free forms such as ``我叫什么``.
    """

    surface = _surface(text)
    if not surface or _looks_like_question(surface):
        return None

    for pattern in _SINGLE_FACT_PATTERNS:
        match = pattern.expression.fullmatch(surface)
        if match is None:
            continue
        value = _clean_value(match.group("value"))
        if value:
            return FactSpec(
                key=pattern.key,
                value=value,
                cardinality="single",
                surface_text=surface,
                correction=pattern.correction,
            )

    for preference, expression in _PREFERENCE_PATTERNS:
        match = expression.fullmatch(surface)
        if match is None:
            continue
        value = _clean_value(match.group("value"))
        if value:
            return FactSpec(
                key=preference_target_key(preference, value),
                value=value,
                cardinality="set",
                surface_text=surface,
            )
    return None


def route_recall(query: str) -> RecallRouteResult:
    """Route a memory query without performing retrieval."""

    surface = _surface(query)
    if not surface:
        return RecallRouteResult(route=RecallRoute.NONE)
    comparable = surface.rstrip("?？").strip()

    if any(pattern.fullmatch(comparable) for pattern in _NAME_RECALL):
        return RecallRouteResult(
            route=RecallRoute.EXACT_FACT,
            fact_key="profile.name",
            cardinality="single",
            reason_code="exact_profile_name_query",
        )

    likes = _LIKE_RECALL.search(comparable) is not None
    dislikes = _DISLIKE_RECALL.search(comparable) is not None
    if likes or dislikes:
        fact_key = "preference"
        if likes and not dislikes:
            fact_key = "preference.like"
        elif dislikes and not likes:
            fact_key = "preference.dislike"
        return RecallRouteResult(
            route=RecallRoute.FACT_SET,
            fact_key=fact_key,
            cardinality="set",
            reason_code="preference_set_query",
        )

    if _TOOL_OR_FILE_QUERY.search(comparable):
        return RecallRouteResult(
            route=RecallRoute.NONE,
            reason_code="non_memory_tool_or_file_query",
        )
    if _RELATIONSHIP_RECALL.search(comparable):
        return RecallRouteResult(
            route=RecallRoute.RELATIONSHIP,
            reason_code="relationship_query",
        )
    if _EPISODIC_RECALL.search(comparable):
        return RecallRouteResult(
            route=RecallRoute.EPISODIC,
            reason_code="episodic_query",
        )
    return RecallRouteResult(route=RecallRoute.NONE)


def forget_fact_key(text: str) -> str | None:
    """Return the exact single-valued fact key named by an explicit forget command."""

    surface = _surface(text).rstrip("。.!！")
    match = _FORGET_FACT.fullmatch(surface)
    if match is None:
        return None
    return _FORGET_KEYS[match.group("field")]


def preference_target_key(preference: PreferenceKind, target: str) -> str:
    """Build a stable key for one set-valued preference target."""

    if preference not in {"like", "dislike"}:
        raise ValueError("preference must be like or dislike")
    normalized = normalize_for_match(target)
    if not normalized:
        raise ValueError("preference target cannot be empty")
    digest = sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"preference.{preference}.{digest}"


def normalize_for_match(text: str) -> str:
    """Normalize text for conservative value-in-response matching."""

    normalized = unicodedata.normalize("NFKC", text).casefold()
    return "".join(character for character in normalized if character.isalnum())


def fact_response_match(fact: FactSpec | str, response: str) -> bool:
    """Return whether a fact value is explicitly present in a response."""

    value = fact.value if isinstance(fact, FactSpec) else fact
    normalized_value = normalize_for_match(value)
    normalized_response = normalize_for_match(response)
    return bool(normalized_value) and normalized_value in normalized_response


def _surface(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return " ".join(normalized.strip().split())


def _clean_value(value: str) -> str:
    return _TRAILING_SENTENCE_MARKS.sub("", " ".join(value.strip().split())).strip(" ,，;；")


def _looks_like_question(text: str) -> bool:
    if text.endswith(("?", "？")):
        return True
    if _QUESTION_WORDS.search(text):
        return True
    return _ENGLISH_QUESTION.match(text) is not None
