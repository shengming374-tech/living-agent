from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from living_agent.models.memory import (
    MemoryCandidateCreate,
    MemoryFactuality,
    MemoryLayer,
    MemoryNode,
    MemoryRecallTraceCreate,
    MemoryRecallTraceItemCreate,
    MemoryStatus,
    MemoryType,
)


def test_dual_layer_fields_are_optional_for_legacy_memory_contracts() -> None:
    candidate = MemoryCandidateCreate(
        type=MemoryType.SEMANTIC,
        content="legacy candidate",
        subject="legacy candidate",
        source_event_ids=["event-1"],
        scope="conversation:napcat:account:group:123",
    )
    node = MemoryNode(
        id="memory-1",
        type=MemoryType.SEMANTIC,
        content="legacy memory",
        subject="legacy memory",
        source_event_ids=["event-1"],
        source_trust="authenticated",
        factuality=MemoryFactuality.REPORTED,
        confidence=0.8,
        importance=0.7,
        scope="conversation:napcat:account:group:123",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        status=MemoryStatus.ACTIVE,
        version=1,
    )

    for memory in (candidate, node):
        assert memory.memory_layer is None
        assert memory.entity_id is None
        assert memory.memory_key is None
        assert memory.valid_until is None
        assert memory.superseded_by_id is None


def test_recall_trace_contract_uses_hashes_and_explicit_layers() -> None:
    trace = MemoryRecallTraceCreate(
        event_id="event-1",
        conversation_id="conversation-1",
        actor_id="actor-1",
        route="hybrid",
        query_hash="a" * 64,
    )
    item = MemoryRecallTraceItemCreate(
        trace_id=trace.trace_id,
        memory_id="memory-1",
        memory_layer=MemoryLayer.FACT,
        selection_reason="ranked",
        final_score=0.81,
        selected=True,
        injected=True,
    )

    assert trace.support_mode == "pending"
    assert trace.response_id is None
    assert trace.context_fingerprint is None
    assert item.memory_layer is MemoryLayer.FACT
    assert item.response_match is None
    assert not item.source_overlap

    with pytest.raises(ValidationError):
        MemoryRecallTraceCreate.model_validate(
            {
                "event_id": "event-1",
                "conversation_id": "conversation-1",
                "actor_id": "actor-1",
                "route": "hybrid",
                "query_hash": "raw query",
            }
        )
