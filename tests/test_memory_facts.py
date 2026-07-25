# ruff: noqa: RUF001

from __future__ import annotations

import pytest

from living_agent.memory.facts import (
    FACT_SCHEMA,
    FactSpec,
    RecallRoute,
    extract_fact,
    fact_response_match,
    forget_fact_key,
    normalize_for_match,
    preference_target_key,
    route_recall,
)


def test_extracts_shengming_as_structured_name_fact() -> None:
    fact = extract_fact("我叫盛茗")

    assert fact == FactSpec(
        key="profile.name",
        value="盛茗",
        cardinality="single",
        surface_text="我叫盛茗",
    )
    assert fact.content == {
        "schema": FACT_SCHEMA,
        "key": "profile.name",
        "value": "盛茗",
        "cardinality": "single",
        "surface_text": "我叫盛茗",
    }


@pytest.mark.parametrize(
    "text",
    [
        "我叫什么",
        "我叫什么？",
        "我的名字是什么",
        "what is my name",
        "Who am I?",
    ],
)
def test_questions_are_never_extracted_as_facts(text: str) -> None:
    assert extract_fact(text) is None


@pytest.mark.parametrize(
    ("query", "expected_key"),
    [
        ("我叫什么", "profile.name"),
        ("我的名字是什么？", "profile.name"),
        ("你还记得我叫什么吗", "profile.name"),
        ("what is my name?", "profile.name"),
        ("Who am I", "profile.name"),
    ],
)
def test_name_questions_use_exact_fact_route(query: str, expected_key: str) -> None:
    result = route_recall(query)

    assert result.route is RecallRoute.EXACT_FACT
    assert result.fact_key == expected_key
    assert result.cardinality == "single"


@pytest.mark.parametrize(
    "query",
    [
        "桌面上有什么？调用 shell 去看看",
        "运行终端命令看看桌面文件",
        "Use the shell to list desktop files",
        "今天天气怎么样？",
        "帮我写一段代码",
    ],
)
def test_tool_file_and_unrelated_queries_do_not_recall_memory(query: str) -> None:
    assert route_recall(query).route is RecallRoute.NONE


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("我现在叫盛茗", "盛茗"),
        ("我改成盛茗了", "盛茗"),
        ("我不是小明，是盛茗", "盛茗"),
        ("我以前叫小明，现在叫盛茗", "盛茗"),
        ("My name is now Shengming", "Shengming"),
        ("Call me Shengming instead", "Shengming"),
        ("My name is not Ming but Shengming", "Shengming"),
    ],
)
def test_explicit_name_corrections_are_marked(text: str, value: str) -> None:
    fact = extract_fact(text)

    assert fact is not None
    assert fact.key == "profile.name"
    assert fact.value == value
    assert fact.correction is True


def test_ordinary_contradictory_name_claim_is_not_implicit_correction() -> None:
    fact = extract_fact("我叫小李")

    assert fact is not None
    assert fact.value == "小李"
    assert fact.correction is False


@pytest.mark.parametrize(
    ("text", "key", "value"),
    [
        ("我的昵称是阿茗", "profile.nickname", "阿茗"),
        ("我的生日是5月18日", "profile.birthday", "5月18日"),
        ("我住在上海", "profile.location", "上海"),
        ("我的职业是工程师", "profile.occupation", "工程师"),
        ("My nickname is Mint", "profile.nickname", "Mint"),
        ("I live in Shanghai", "profile.location", "Shanghai"),
        ("I work as an engineer", "profile.occupation", "an engineer"),
    ],
)
def test_supported_single_fact_fields(text: str, key: str, value: str) -> None:
    fact = extract_fact(text)

    assert fact is not None
    assert fact.key == key
    assert fact.value == value
    assert fact.cardinality == "single"


def test_preference_target_keys_are_stable_after_normalization() -> None:
    first = extract_fact("I like Coffee.")
    second = extract_fact("i like coffee")

    assert first is not None
    assert second is not None
    assert first.cardinality == second.cardinality == "set"
    assert first.key == second.key
    assert first.key == preference_target_key("like", "COFFEE")
    assert first.key.startswith("preference.like.")


def test_like_and_dislike_targets_have_distinct_keys() -> None:
    liked = extract_fact("我喜欢咖啡")
    disliked = extract_fact("我讨厌咖啡")

    assert liked is not None
    assert disliked is not None
    assert liked.key != disliked.key
    assert liked.key.startswith("preference.like.")
    assert disliked.key.startswith("preference.dislike.")


@pytest.mark.parametrize(
    ("query", "fact_key"),
    [
        ("我喜欢什么？", "preference.like"),
        ("我讨厌什么", "preference.dislike"),
        ("What do I like?", "preference.like"),
        ("What are my dislikes?", "preference.dislike"),
    ],
)
def test_preference_queries_use_fact_set_route(query: str, fact_key: str) -> None:
    result = route_recall(query)

    assert result.route is RecallRoute.FACT_SET
    assert result.fact_key == fact_key
    assert result.cardinality == "set"


@pytest.mark.parametrize(
    "query",
    [
        "还记得上次发生了什么吗？",
        "我们之前聊了什么？",
        "What happened last time?",
    ],
)
def test_event_recall_uses_episodic_route(query: str) -> None:
    assert route_recall(query).route is RecallRoute.EPISODIC


@pytest.mark.parametrize(
    "query",
    [
        "我的猫叫什么？",
        "我和小明是什么关系？",
        "Who is my mother?",
        "What's my dog's name?",
    ],
)
def test_relationship_questions_use_relationship_route(query: str) -> None:
    assert route_recall(query).route is RecallRoute.RELATIONSHIP


def test_normalization_and_fact_response_match() -> None:
    fact = extract_fact("My name is Alice Smith")

    assert fact is not None
    assert normalize_for_match(" Alice　Smith! ") == "alicesmith"
    assert fact_response_match(fact, "Of course — your name is ALICE SMITH.")
    assert fact_response_match("盛茗", "你叫盛 茗。")
    assert not fact_response_match(fact, "I do not know your name.")


@pytest.mark.parametrize(
    ("command", "memory_key"),
    [
        ("忘记我的名字", "profile.name"),
        ("请删除我的生日这条记忆", "profile.birthday"),
        ("别再记得我的职业", "profile.occupation"),
    ],
)
def test_explicit_forget_command_targets_exact_fact(
    command: str,
    memory_key: str,
) -> None:
    assert forget_fact_key(command) == memory_key


def test_question_is_not_a_forget_command() -> None:
    assert forget_fact_key("你还记得我的名字吗") is None
