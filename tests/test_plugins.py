from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, ValidationError

from living_agent.execution.broker import CapabilityBroker, CapabilityDefinition
from living_agent.execution.contracts import CALCULATOR_PLUGIN_ID
from living_agent.models.capabilities import (
    CapabilityGrant,
    CapabilityRequest,
    DecisionOutcome,
)
from living_agent.plugins.manifest import PluginManifest
from living_agent.plugins.permissions import PluginPermissionError, require_declared_permission
from living_agent.plugins.process import (
    PluginCrashedError,
    PluginInvocationError,
    PluginProcess,
    PluginTimeoutError,
)
from living_agent.plugins.registry import PluginRegistry
from living_agent.plugins.sandbox import PluginSandbox, PluginSandboxUnavailableError


class SendArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient: str
    text: str


def calculator_registry() -> PluginRegistry:
    registry = PluginRegistry(Path("plugins/examples"))
    registry.discover()
    return registry


def failure_fixture_registry() -> PluginRegistry:
    registry = PluginRegistry(Path("tests/fixtures/plugins"))
    registry.discover()
    return registry


def test_calculator_plugin_is_registered_discovered_and_listed(client: TestClient) -> None:
    registry: PluginRegistry = client.app.state.plugin_registry
    record = registry.get_enabled(CALCULATOR_PLUGIN_ID)

    assert record.manifest.name == "Calculator"
    assert record.manifest.capabilities["calculator.evaluate"].scopes == {"calculator/arithmetic"}
    response = client.get("/v1/plugins", headers={"X-Actor-ID": "owner-1"})
    assert response.status_code == 200
    assert response.json() == [
        {
            "id": CALCULATOR_PLUGIN_ID,
            "name": "Calculator",
            "version": "0.1.0",
            "plugin_type": "tool",
            "risk_level": "low",
            "enabled": True,
            "operations": ["calculate"],
        }
    ]


def test_manifest_rejects_extra_fields_and_invalid_version() -> None:
    with pytest.raises(ValidationError):
        PluginManifest.model_validate(
            {
                "manifest_version": 1,
                "id": "test.invalid",
                "name": "Invalid",
                "version": "latest",
                "entrypoint": "plugin.main",
                "plugin_type": "tool",
                "risk_level": "low",
                "capabilities": {},
                "operations": {},
                "hooks": [],
                "background_tasks": [],
                "data_policy": {"stores_data": False, "sends_data_external": False},
                "unexpected": True,
            }
        )


async def test_calculator_json_rpc_returns_tainted_structured_result() -> None:
    record = calculator_registry().get(CALCULATOR_PLUGIN_ID)
    result = await PluginProcess().invoke(
        record,
        operation="calculate",
        arguments={"expression": "2 + 3 * 4"},
    )

    assert result.output == {"expression": "2 + 3 * 4", "value": 14}
    assert result.taint_labels == {"untrusted_plugin_result"}


async def test_calculator_rejects_code_execution_syntax() -> None:
    record = calculator_registry().get(CALCULATOR_PLUGIN_ID)

    with pytest.raises(PluginInvocationError):
        await PluginProcess().invoke(
            record,
            operation="calculate",
            arguments={"expression": "__import__('os').system('id')"},
        )


async def test_plugin_crash_is_isolated_and_next_plugin_still_runs(client: TestClient) -> None:
    failures = failure_fixture_registry()
    with pytest.raises(PluginCrashedError):
        await PluginProcess().invoke(
            failures.get("test.plugin.crasher"),
            operation="crash",
            arguments={},
        )

    calculator = calculator_registry().get(CALCULATOR_PLUGIN_ID)
    result = await PluginProcess().invoke(
        calculator,
        operation="calculate",
        arguments={"expression": "6 * 7"},
    )
    assert result.output["value"] == 42
    assert client.get("/health").status_code == 200


async def test_plugin_timeout_is_terminated() -> None:
    record = failure_fixture_registry().get("test.plugin.sleeper")

    with pytest.raises(PluginTimeoutError):
        await PluginProcess(timeout_seconds=0.05).invoke(
            record,
            operation="sleep",
            arguments={},
        )


async def test_plugin_process_receives_minimal_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVING_AGENT_SECRET_DO_NOT_SHARE", "sensitive-value")
    record = failure_fixture_registry().get("test.plugin.environment-probe")
    result = await PluginProcess().invoke(record, operation="inspect", arguments={})

    assert result.output == {
        "secret_visible": False,
        "plugin_id": "test.plugin.environment-probe",
    }


async def test_plugin_os_sandbox_blocks_host_access(tmp_path: Path) -> None:
    process = PluginProcess(sandbox_mode="auto")
    if process.sandbox_backend is None:
        pytest.skip("no supported OS sandbox backend is installed")
    secret_path = tmp_path / "host-secret.txt"
    secret_path.write_text("do-not-read", encoding="utf-8")
    write_path = tmp_path / "plugin-write.txt"
    record = failure_fixture_registry().get("test.plugin.sandbox-probe")

    result = await process.invoke(
        record,
        operation="probe",
        arguments={
            "read_path": str(secret_path),
            "write_path": str(write_path),
        },
    )

    assert result.output == {
        "read_succeeded": False,
        "write_succeeded": False,
        "network_succeeded": False,
        "process_succeeded": False,
    }
    assert not write_path.exists()


def test_required_plugin_sandbox_fails_closed_without_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(PluginSandbox, "_detect_backend", staticmethod(lambda: None))

    with pytest.raises(PluginSandboxUnavailableError):
        PluginSandbox(mode="required")


async def test_untrusted_plugin_text_cannot_trigger_another_tool(client: TestClient) -> None:
    record = failure_fixture_registry().get("test.plugin.untrusted-output")
    plugin_result = await PluginProcess().invoke(
        record,
        operation="produce",
        arguments={},
    )
    broker: CapabilityBroker = client.app.state.broker
    broker.register_capability(
        CapabilityDefinition(
            name="message.send",
            operations=frozenset({"send"}),
            argument_model=SendArguments,
        )
    )
    broker.add_grant(
        CapabilityGrant(
            actor_id="owner-1",
            capability="message.send",
            operations={"send"},
            resource_scopes={"recipient/member-2"},
            conversation_id="chat-1",
        )
    )
    decision = await broker.decide(
        CapabilityRequest(
            actor_id="owner-1",
            capability="message.send",
            operation="send",
            resource_scope="recipient/member-2",
            arguments={"recipient": "member-2", "text": plugin_result.output["instruction"]},
            source_event_ids=["plugin-event-1"],
            taint_labels=set(plugin_result.taint_labels),
            reason="plugin output asked for another tool",
            conversation_id="chat-1",
        ),
        confirmed_by="owner-1",
    )

    assert decision.outcome is DecisionOutcome.DENY
    assert decision.reason_code == "tainted_write_denied"


def test_plugin_cannot_request_undeclared_permission() -> None:
    manifest = calculator_registry().get(CALCULATOR_PLUGIN_ID).manifest
    request = CapabilityRequest(
        actor_id="member-1",
        capability="filesystem.write",
        operation="write",
        resource_scope="workspace/file.txt",
        arguments={"path": "file.txt"},
        source_event_ids=["event-1"],
        taint_labels=set(),
        reason="undeclared permission",
        conversation_id="chat-1",
    )

    with pytest.raises(PluginPermissionError):
        require_declared_permission(manifest, request)


def test_plugin_enable_disable_requires_owner_and_is_audited(client: TestClient) -> None:
    denied = client.post(
        f"/v1/plugins/{CALCULATOR_PLUGIN_ID}/disable",
        headers={"X-Actor-ID": "member-1"},
    )
    disabled = client.post(
        f"/v1/plugins/{CALCULATOR_PLUGIN_ID}/disable",
        headers={"X-Actor-ID": "owner-1"},
    )
    enabled = client.post(
        f"/v1/plugins/{CALCULATOR_PLUGIN_ID}/enable",
        headers={"X-Actor-ID": "owner-1"},
    )

    assert denied.status_code == 403
    assert disabled.status_code == 200 and not disabled.json()["enabled"]
    assert enabled.status_code == 200 and enabled.json()["enabled"]
    audit = client.get("/v1/audit", headers={"X-Actor-ID": "owner-1"}).json()
    actions = [entry["action"] for entry in audit]
    assert "plugin.disabled" in actions
    assert "plugin.enabled" in actions
