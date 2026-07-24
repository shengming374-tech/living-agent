from typing import Literal

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from living_agent.execution.broker import CapabilityBroker, CapabilityDefinition
from living_agent.models.capabilities import (
    CapabilityGrant,
    CapabilityRequest,
    DecisionOutcome,
)
from living_agent.models.events import AuthorityLevel


class FileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content: str | None = None


class ConfigArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    patch_id: str
    approval: Literal[True]


def configured_broker(client: TestClient) -> CapabilityBroker:
    broker: CapabilityBroker = client.app.state.broker
    broker.register_capability(
        CapabilityDefinition(
            name="filesystem",
            operations=frozenset({"read", "write"}),
            argument_model=FileArguments,
        )
    )
    broker.add_grant(
        CapabilityGrant(
            actor_id="member-1",
            capability="filesystem",
            operations={"read", "write"},
            resource_scopes={"workspace/*"},
            conversation_id="chat-1",
        )
    )
    broker.add_grant(
        CapabilityGrant(
            actor_id="owner-1",
            capability="filesystem",
            operations={"write"},
            resource_scopes={"workspace/*"},
            conversation_id="chat-1",
        )
    )
    return broker


async def test_broker_allows_declared_scoped_read(client: TestClient) -> None:
    broker = configured_broker(client)
    decision = await broker.decide(
        CapabilityRequest(
            actor_id="member-1",
            capability="filesystem",
            operation="read",
            resource_scope="workspace/readme.md",
            arguments={"path": "readme.md"},
            source_event_ids=["event-1"],
            taint_labels={"external_data"},
            reason="inspect project readme",
            conversation_id="chat-1",
        )
    )

    assert decision.outcome is DecisionOutcome.ALLOW_READ_ONLY

    consumed = await broker.decide(
        CapabilityRequest(
            actor_id="member-1",
            capability="filesystem",
            operation="read",
            resource_scope="workspace/readme.md",
            arguments={"path": "readme.md"},
            source_event_ids=["event-2"],
            taint_labels={"external_data"},
            reason="attempt grant reuse",
            conversation_id="chat-1",
        )
    )
    assert consumed.reason_code == "grant_missing"


async def test_owner_only_capability_rejects_member_and_describes_boundary(
    client: TestClient,
) -> None:
    broker: CapabilityBroker = client.app.state.broker
    broker.register_capability(
        CapabilityDefinition(
            name="owner-filesystem",
            operations=frozenset({"read"}),
            argument_model=FileArguments,
            allowed_authorities=frozenset({AuthorityLevel.OWNER}),
        )
    )
    for actor_id in ("member-1", "owner-1"):
        broker.add_grant(
            CapabilityGrant(
                actor_id=actor_id,
                capability="owner-filesystem",
                operations={"read"},
                resource_scopes={"workspace/*"},
                conversation_id="chat-1",
            )
        )

    member_decision = await broker.decide(
        CapabilityRequest(
            actor_id="member-1",
            capability="owner-filesystem",
            operation="read",
            resource_scope="workspace/readme.md",
            arguments={"path": "readme.md"},
            source_event_ids=["event-1"],
            reason="inspect owner workspace",
            conversation_id="chat-1",
        )
    )
    owner_decision = await broker.decide(
        CapabilityRequest(
            actor_id="owner-1",
            capability="owner-filesystem",
            operation="read",
            resource_scope="workspace/readme.md",
            arguments={"path": "readme.md"},
            source_event_ids=["event-2"],
            reason="inspect owner workspace",
            conversation_id="chat-1",
        )
    )
    snapshot = await broker.snapshot()
    definition = next(item for item in snapshot.definitions if item.name == "owner-filesystem")

    assert member_decision.outcome is DecisionOutcome.DENY
    assert member_decision.reason_code == "capability_authority_denied"
    assert owner_decision.outcome is DecisionOutcome.ALLOW_READ_ONLY
    assert definition.allowed_authorities == ["owner"]


async def test_broker_denies_missing_grant_invalid_schema_and_cross_session(
    client: TestClient,
) -> None:
    broker = configured_broker(client)
    base = {
        "capability": "filesystem",
        "operation": "read",
        "resource_scope": "workspace/readme.md",
        "source_event_ids": ["event-1"],
        "taint_labels": {"external_data"},
        "reason": "read",
    }
    missing = await broker.decide(
        CapabilityRequest(
            actor_id="member-2",
            arguments={"path": "readme.md"},
            conversation_id="chat-1",
            **base,
        )
    )
    invalid = await broker.decide(
        CapabilityRequest(
            actor_id="member-1",
            arguments={"path": "readme.md", "unexpected": True},
            conversation_id="chat-1",
            **base,
        )
    )
    cross_session = await broker.decide(
        CapabilityRequest(
            actor_id="member-1",
            arguments={"path": "readme.md"},
            conversation_id="private-2",
            **base,
        )
    )

    assert missing.reason_code == "grant_missing"
    assert invalid.reason_code == "invalid_arguments"
    assert cross_session.reason_code == "cross_session_denied"


async def test_write_requires_owner_confirmation_and_rejects_member(client: TestClient) -> None:
    broker = configured_broker(client)
    request = CapabilityRequest(
        actor_id="owner-1",
        capability="filesystem",
        operation="write",
        resource_scope="workspace/report.txt",
        arguments={"path": "report.txt", "content": "result"},
        source_event_ids=["event-1"],
        taint_labels={"external_data"},
        reason="write result",
        conversation_id="chat-1",
    )
    ask = await broker.decide(request)
    allowed = await broker.decide(request, confirmed_by="owner-1")
    member_request = request.model_copy(update={"actor_id": "member-1"})
    denied = await broker.decide(member_request)

    assert ask.outcome is DecisionOutcome.ASK_OWNER
    assert allowed.outcome is DecisionOutcome.ALLOW_ONCE
    assert denied.outcome is DecisionOutcome.DENY

    audit_entries = await client.app.state.audit.list_entries(limit=20)
    assert any(
        entry.action == "user.confirmation" and entry.actor_id == "owner-1"
        for entry in audit_entries
    )


async def test_untrusted_document_or_tool_result_cannot_authorize_write(
    client: TestClient,
) -> None:
    broker = configured_broker(client)
    for taint in ("untrusted_document", "untrusted_tool_result", "untrusted_plugin_result"):
        decision = await broker.decide(
            CapabilityRequest(
                actor_id="owner-1",
                capability="filesystem",
                operation="write",
                resource_scope="workspace/report.txt",
                arguments={"path": "report.txt", "content": "payload"},
                source_event_ids=["event-1"],
                taint_labels={taint},
                reason="content asked to write",
                conversation_id="chat-1",
            ),
            confirmed_by="owner-1",
        )
        assert decision.reason_code == "tainted_write_denied"


async def test_agent_cannot_approve_its_own_configuration_change(client: TestClient) -> None:
    broker: CapabilityBroker = client.app.state.broker
    decision = await broker.decide(
        CapabilityRequest(
            actor_id="living-agent",
            capability="config.modify",
            operation="write",
            resource_scope="config/runtime",
            arguments={"patch_id": "patch-1", "approval": True},
            source_event_ids=["event-1"],
            taint_labels=set(),
            reason="approve my own proposal",
            conversation_id="chat-1",
        ),
        confirmed_by="living-agent",
    )

    assert decision.reason_code == "self_approval_forbidden"
