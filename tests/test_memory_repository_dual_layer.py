from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from living_agent.memory.repository import MemoryNotFoundError, MemoryRepository
from living_agent.models.memory import (
    CandidateStatus,
    MemoryCandidate,
    MemoryCandidateCreate,
    MemoryFactuality,
    MemoryLayer,
    MemoryMergeRequest,
    MemoryRecallTraceCreate,
    MemoryRecallTraceItemCreate,
    MemorySplitPart,
    MemorySplitRequest,
    MemorySupportMode,
    MemoryType,
)
from living_agent.storage.database import Base, Database


@pytest.fixture
async def repository(tmp_path: Path) -> AsyncIterator[MemoryRepository]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'memory-repository.db'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield MemoryRepository(database.sessions)
    finally:
        await database.dispose()


async def _candidate(
    repository: MemoryRepository,
    *,
    candidate_id: str,
    content: str | dict[str, str],
    subject: str,
    source_event_ids: list[str],
    scope: str = "conversation:chat-a",
    confidence: float = 0.7,
    memory_layer: MemoryLayer | None = None,
    entity_id: str | None = None,
    memory_key: str | None = None,
    valid_until: datetime | None = None,
) -> MemoryCandidate:
    return await repository.create_candidate(
        MemoryCandidateCreate(
            candidate_id=candidate_id,
            type=MemoryType.SEMANTIC,
            content=content,
            subject=subject,
            source_event_ids=source_event_ids,
            factuality=MemoryFactuality.REPORTED,
            confidence=confidence,
            importance=0.7,
            scope=scope,
            memory_layer=memory_layer,
            entity_id=entity_id,
            memory_key=memory_key,
            valid_until=valid_until,
        ),
        proposer_id="member-1",
        source_trust="authenticated",
    )


@pytest.mark.asyncio
async def test_candidate_commit_maps_dual_layer_fields_and_links_supersession(
    repository: MemoryRepository,
) -> None:
    valid_until = datetime.now(UTC) + timedelta(days=30)
    original_candidate = await _candidate(
        repository,
        candidate_id="candidate-original",
        content={"schema": "social.fact.v1", "value": "Alice"},
        subject="member name",
        source_event_ids=["event-1"],
        memory_layer=MemoryLayer.FACT,
        entity_id="member-1",
        memory_key="profile.name",
        valid_until=valid_until,
    )
    assert original_candidate.memory_layer is MemoryLayer.FACT
    assert original_candidate.entity_id == "member-1"
    assert original_candidate.memory_key == "profile.name"
    assert original_candidate.valid_until == valid_until

    _, original = await repository.commit_candidate(
        original_candidate.candidate_id,
        factuality=MemoryFactuality.REPORTED,
        actor_id="owner-1",
    )
    replacement_candidate = await _candidate(
        repository,
        candidate_id="candidate-replacement",
        content={"schema": "social.fact.v1", "value": "Alicia"},
        subject="member name",
        source_event_ids=["event-2"],
        memory_layer=MemoryLayer.FACT,
        entity_id="member-1",
        memory_key="profile.name",
    )
    _, replacement = await repository.commit_candidate(
        replacement_candidate.candidate_id,
        factuality=MemoryFactuality.REPORTED,
        actor_id="owner-1",
        supersede_memory_ids=[original.id],
    )

    superseded = await repository.get(original.id)
    assert replacement.memory_layer is MemoryLayer.FACT
    assert replacement.entity_id == "member-1"
    assert replacement.memory_key == "profile.name"
    assert superseded.status.value == "deleted"
    assert superseded.superseded_by_id == replacement.id
    assert [version.change_type for version in await repository.versions(original.id)] == [
        "created",
        "superseded",
    ]


@pytest.mark.asyncio
async def test_merge_and_split_outputs_default_to_narrative_layer(
    repository: MemoryRepository,
) -> None:
    await _candidate(
        repository,
        candidate_id="candidate-1",
        content="first",
        subject="first",
        source_event_ids=["event-1"],
    )
    await _candidate(
        repository,
        candidate_id="candidate-2",
        content="second",
        subject="second",
        source_event_ids=["event-2"],
    )
    _, first = await repository.commit_candidate(
        "candidate-1",
        factuality=MemoryFactuality.REPORTED,
        actor_id="owner-1",
    )
    _, second = await repository.commit_candidate(
        "candidate-2",
        factuality=MemoryFactuality.REPORTED,
        actor_id="owner-1",
    )

    merged = await repository.merge(
        MemoryMergeRequest(
            memory_ids=[first.id, second.id],
            type=MemoryType.SEMANTIC,
            content="combined",
            subject="combined",
            factuality=MemoryFactuality.REPORTED,
            confidence=0.8,
            importance=0.8,
            scope="conversation:chat-a",
        ),
        actor_id="owner-1",
    )
    assert merged.memory_layer is MemoryLayer.NARRATIVE
    assert merged.entity_id is None
    assert merged.memory_key is None

    outputs = await repository.split(
        merged.id,
        MemorySplitRequest(
            parts=[
                MemorySplitPart(
                    type=MemoryType.SEMANTIC,
                    content="left",
                    subject="left",
                    factuality=MemoryFactuality.REPORTED,
                    confidence=0.7,
                    importance=0.6,
                    scope="conversation:chat-a",
                ),
                MemorySplitPart(
                    type=MemoryType.SEMANTIC,
                    content="right",
                    subject="right",
                    factuality=MemoryFactuality.REPORTED,
                    confidence=0.7,
                    importance=0.6,
                    scope="conversation:chat-a",
                ),
            ]
        ),
        actor_id="owner-1",
    )
    assert [item.memory_layer for item in outputs] == [
        MemoryLayer.NARRATIVE,
        MemoryLayer.NARRATIVE,
    ]
    assert all(item.entity_id is None and item.memory_key is None for item in outputs)


@pytest.mark.asyncio
async def test_normalize_fact_is_idempotent_and_exact_fact_reuses_scope_rules(
    repository: MemoryRepository,
) -> None:
    await _candidate(
        repository,
        candidate_id="candidate-legacy",
        content="我叫小明",
        subject="legacy name",
        source_event_ids=["event-1"],
    )
    _, legacy = await repository.commit_candidate(
        "candidate-legacy",
        factuality=MemoryFactuality.REPORTED,
        actor_id="owner-1",
    )
    structured = {
        "schema": "social.fact.v1",
        "key": "profile.name",
        "value": "小明",
        "cardinality": "single",
        "surface_text": "我叫小明",
    }

    migrated = await repository.normalize_fact(
        legacy.id,
        structured,
        "member-1",
        "profile.name",
        "owner-1",
    )
    repeated = await repository.normalize_fact(
        legacy.id,
        structured,
        "member-1",
        "profile.name",
        "owner-1",
    )

    assert migrated.memory_layer is MemoryLayer.FACT
    assert migrated.content == structured
    assert migrated.version == 2
    assert repeated.version == 2
    assert [version.change_type for version in await repository.versions(legacy.id)] == [
        "created",
        "migrated",
    ]
    assert (
        await repository.exact_fact(
            entity_id="member-1",
            memory_key="profile.name",
            actor_id="member-1",
            conversation_id="chat-a",
            owner=False,
        )
    ).id == legacy.id
    assert (
        await repository.exact_fact(
            entity_id="member-1",
            memory_key="profile.name",
            actor_id="member-1",
            conversation_id="chat-b",
            owner=False,
        )
        is None
    )
    assert (
        await repository.exact_fact(
            entity_id="member-1",
            memory_key="profile.name",
            actor_id="owner-1",
            conversation_id=None,
            owner=True,
        )
    ).id == legacy.id


@pytest.mark.asyncio
async def test_recall_trace_create_get_list_and_complete_are_consistent(
    repository: MemoryRepository,
) -> None:
    trace = MemoryRecallTraceCreate(
        trace_id="trace-1",
        event_id="event-1",
        conversation_id="chat-a",
        actor_id="member-1",
        route="exact_fact",
        query_hash="a" * 64,
    )
    created = await repository.create_recall_trace(
        trace,
        [
            MemoryRecallTraceItemCreate(
                row_id="row-1",
                trace_id=trace.trace_id,
                memory_id="memory-1",
                memory_layer=MemoryLayer.FACT,
                selection_reason="exact_key",
                final_score=1.0,
                selected=True,
            ),
            MemoryRecallTraceItemCreate(
                row_id="row-2",
                trace_id=trace.trace_id,
                memory_id="memory-2",
                memory_layer=MemoryLayer.NARRATIVE,
                selection_reason="lexical",
                final_score=0.5,
            ),
        ],
    )
    assert created.trace.support_mode is MemorySupportMode.PENDING
    assert [item.memory_id for item in created.items] == ["memory-1", "memory-2"]
    fetched = await repository.get_recall_trace(trace.trace_id)
    assert fetched.trace.trace_id == created.trace.trace_id
    assert [item.memory_id for item in fetched.items] == ["memory-1", "memory-2"]

    second = MemoryRecallTraceCreate(
        trace_id="trace-2",
        event_id="event-2",
        conversation_id="chat-a",
        actor_id="member-1",
        route="none",
        query_hash="b" * 64,
    )
    await repository.create_recall_trace(second, [])
    assert [
        item.trace_id for item in await repository.list_recall_traces(limit=1)
    ] == ["trace-2"]

    with pytest.raises(MemoryNotFoundError):
        await repository.complete_recall_trace(
            trace.trace_id,
            response_id="response-1",
            context_fingerprint="c" * 64,
            support_mode=MemorySupportMode.CORROBORATED,
            item_updates={"missing": {"injected": True}},
        )
    assert (await repository.get_recall_trace(trace.trace_id)).trace.support_mode is (
        MemorySupportMode.PENDING
    )

    staged = await repository.complete_recall_trace(
        trace.trace_id,
        context_fingerprint="c" * 64,
        item_updates={
            "memory-1": {"injected": True},
            "memory-2": {"injected": False},
        },
    )
    assert staged.trace.response_id is None
    assert staged.trace.support_mode is MemorySupportMode.PENDING
    assert staged.trace.context_fingerprint == "c" * 64

    completed = await repository.complete_recall_trace(
        trace.trace_id,
        response_id="response-1",
        support_mode=MemorySupportMode.CORROBORATED,
        item_updates={
            "memory-1": {"response_match": True, "source_overlap": True},
            "memory-2": {"response_match": False},
        },
    )
    by_id = {item.memory_id: item for item in completed.items}
    assert completed.trace.response_id == "response-1"
    assert completed.trace.context_fingerprint == "c" * 64
    assert completed.trace.support_mode is MemorySupportMode.CORROBORATED
    assert by_id["memory-1"].injected
    assert by_id["memory-1"].response_match
    assert by_id["memory-1"].source_overlap
    assert by_id["memory-2"].response_match is False


@pytest.mark.asyncio
async def test_apply_existing_fact_confirms_or_corrects_in_place(
    repository: MemoryRepository,
) -> None:
    original_content = {
        "schema": "social.fact.v1",
        "key": "profile.name",
        "value": "小明",
        "cardinality": "single",
        "surface_text": "我叫小明",
    }
    await _candidate(
        repository,
        candidate_id="candidate-original",
        content=original_content,
        subject="member name",
        source_event_ids=["event-1"],
        confidence=0.7,
        memory_layer=MemoryLayer.FACT,
        entity_id="member-1",
        memory_key="profile.name",
    )
    _, original = await repository.commit_candidate(
        "candidate-original",
        factuality=MemoryFactuality.REPORTED,
        actor_id="owner-1",
    )

    await _candidate(
        repository,
        candidate_id="candidate-confirm",
        content=original_content,
        subject="member name",
        source_event_ids=["event-1", "event-2"],
        confidence=0.8,
        memory_layer=MemoryLayer.FACT,
        entity_id="member-1",
        memory_key="profile.name",
    )
    confirmation = await repository.apply_existing_fact(
        "candidate-confirm",
        "owner-1",
        False,
    )
    assert confirmation is not None
    confirmed_candidate, confirmed, outcome = confirmation
    assert outcome == "confirmed"
    assert confirmed_candidate.status is CandidateStatus.COMMITTED
    assert confirmed.source_event_ids == ["event-1", "event-2"]
    assert confirmed.confidence == pytest.approx(0.85)
    assert confirmed.version == 2

    corrected_content = {
        **original_content,
        "value": "小李",
        "surface_text": "我现在叫小李",
    }
    await _candidate(
        repository,
        candidate_id="candidate-correction",
        content=corrected_content,
        subject="member name",
        source_event_ids=["event-3"],
        confidence=0.76,
        memory_layer=MemoryLayer.FACT,
        entity_id="member-1",
        memory_key="profile.name",
    )
    assert (
        await repository.apply_existing_fact(
            "candidate-correction",
            "owner-1",
            False,
        )
        is None
    )
    assert (await repository.get_candidate("candidate-correction")).status is (
        CandidateStatus.PENDING
    )
    assert (await repository.get(original.id)).content == original_content

    correction = await repository.apply_existing_fact(
        "candidate-correction",
        "owner-1",
        True,
    )
    assert correction is not None
    corrected_candidate, corrected, outcome = correction
    assert outcome == "corrected"
    assert corrected_candidate.status is CandidateStatus.COMMITTED
    assert corrected.content == corrected_content
    assert corrected.source_event_ids == ["event-1", "event-2", "event-3"]
    assert corrected.confidence == pytest.approx(0.76)
    assert corrected.version == 3
    assert [version.change_type for version in await repository.versions(original.id)] == [
        "created",
        "confirmed",
        "corrected",
    ]
