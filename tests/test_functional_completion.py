"""Regression coverage for persisted controls and daily-plan activity linkage."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from living_agent.app import create_app
from living_agent.config import Settings
from living_agent.execution.contracts import CALCULATOR_PLUGIN_ID
from living_agent.plugins.registry import PluginDisabledError, PluginRegistry

OWNER_HEADERS = {"X-Actor-ID": "owner-1"}


def _save_plan(
    client: TestClient,
    plan_date: str,
    *,
    item_id: str = "routine",
    status: str = "planned",
    expected_version: int | None = None,
) -> dict[str, object]:
    response = client.put(
        f"/v1/life/daily-plans/{plan_date}",
        headers=OWNER_HEADERS,
        json={
            "intention": "记录当前计划的执行状态",
            "expected_version": expected_version,
            "items": [
                {"item_id": item_id, "title": "整理记录", "kind": "routine", "status": status}
            ],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _status(client: TestClient, plan_date: str, version: int, status: str) -> None:
    response = client.post(
        f"/v1/life/daily-plans/{plan_date}/items/routine/status",
        headers=OWNER_HEADERS,
        json={"expected_version": version, "status": status},
    )
    assert response.status_code == 200, response.text


def _activities(client: TestClient) -> list[dict[str, object]]:
    response = client.get("/v1/life/activities", headers=OWNER_HEADERS)
    assert response.status_code == 200
    return response.json()


def test_same_item_id_in_another_day_keeps_activity_scope(client: TestClient) -> None:
    first = _save_plan(client, "2030-04-01", status="in_progress")
    second = _save_plan(client, "2030-04-02")
    _status(client, "2030-04-02", 1, "completed")

    activities = {item["plan_id"]: item for item in _activities(client)}
    assert activities[first["plan_id"]]["status"] == "running"
    assert activities[second["plan_id"]]["status"] == "completed"


def test_replacing_running_plan_item_closes_old_activity(client: TestClient) -> None:
    _save_plan(client, "2030-04-03", status="in_progress")
    _save_plan(client, "2030-04-03", item_id="replacement", expected_version=1)

    activities = _activities(client)
    assert len(activities) == 1
    assert activities[0]["plan_item_id"] == "routine"
    assert activities[0]["status"] == "cancelled"
    assert activities[0]["finished_at"] is not None


def test_plan_reset_and_bulk_completion_close_activities(client: TestClient) -> None:
    _save_plan(client, "2030-04-04", status="in_progress")
    _status(client, "2030-04-04", 1, "planned")
    _status(client, "2030-04-04", 2, "in_progress")
    _save_plan(client, "2030-04-04", status="completed", expected_version=3)

    activities = _activities(client)
    assert sorted(item["status"] for item in activities) == ["cancelled", "completed"]
    assert all(item["finished_at"] is not None for item in activities)


def test_repeated_completion_preserves_single_activity(client: TestClient) -> None:
    _save_plan(client, "2030-04-05")
    _status(client, "2030-04-05", 1, "completed")
    _status(client, "2030-04-05", 2, "completed")
    _save_plan(client, "2030-04-05", status="completed", expected_version=3)

    activities = _activities(client)
    assert len(activities) == 1
    assert activities[0]["status"] == "completed"


@pytest.mark.parametrize("field", ["title", "summary", "goals", "status"])
def test_project_null_update_is_rejected_without_mutation(
    client: TestClient, field: str
) -> None:
    created = client.post(
        "/v1/life/projects",
        headers=OWNER_HEADERS,
        json={"title": "项目", "summary": "保留有效字段"},
    )
    assert created.status_code == 201
    project = created.json()
    path = f"/v1/life/projects/{project['project_id']}"
    before = client.get(path, headers=OWNER_HEADERS).json()

    invalid = client.patch(path, headers=OWNER_HEADERS, json={"expected_version": 1, field: None})
    assert invalid.status_code == 422
    assert client.get(path, headers=OWNER_HEADERS).json() == before


@pytest.mark.asyncio
async def test_plugin_disable_survives_configured_default_on_restart(
    client: TestClient, tmp_path: Path
) -> None:
    plugin_root = Path(__file__).parent.parent / "plugins" / "examples"
    state_path = tmp_path / "plugin-state.json"
    audit = client.app.state.audit
    registry = PluginRegistry(plugin_root, state_path=state_path)
    registry.discover()
    await registry.initialize(
        default_enabled=[CALCULATOR_PLUGIN_ID], actor_id="owner-1", audit=audit
    )
    await registry.disable(CALCULATOR_PLUGIN_ID, actor_id="owner-1", audit=audit)

    restored = PluginRegistry(plugin_root, state_path=state_path)
    restored.discover()
    await restored.initialize(
        default_enabled=[CALCULATOR_PLUGIN_ID], actor_id="owner-1", audit=audit
    )

    with pytest.raises(PluginDisabledError):
        restored.get_enabled(CALCULATOR_PLUGIN_ID)
    assert restored.summaries()[0].enabled is False


@pytest.mark.asyncio
async def test_plugin_enable_survives_restart_without_configured_default(
    client: TestClient, tmp_path: Path
) -> None:
    plugin_root = Path(__file__).parent.parent / "plugins" / "examples"
    state_path = tmp_path / "plugin-state.json"
    audit = client.app.state.audit
    registry = PluginRegistry(plugin_root, state_path=state_path)
    registry.discover()
    await registry.initialize(default_enabled=[], actor_id="owner-1", audit=audit)
    await registry.enable(CALCULATOR_PLUGIN_ID, actor_id="owner-1", audit=audit)

    restored = PluginRegistry(plugin_root, state_path=state_path)
    restored.discover()
    await restored.initialize(default_enabled=[], actor_id="owner-1", audit=audit)

    assert restored.get_enabled(CALCULATOR_PLUGIN_ID).manifest.id == CALCULATOR_PLUGIN_ID


@pytest.mark.asyncio
async def test_unknown_plugin_toggle_does_not_write_state(
    client: TestClient, tmp_path: Path
) -> None:
    state_path = tmp_path / "plugin-state.json"
    registry = PluginRegistry(Path("plugins/examples"), state_path=state_path)
    registry.discover()
    with pytest.raises(KeyError):
        await registry.enable("missing-plugin", actor_id="owner-1", audit=client.app.state.audit)
    assert not state_path.exists()


def test_plugin_toggle_api_restores_state_in_a_new_app(settings: Settings) -> None:
    with TestClient(create_app(settings)) as first:
        disabled = first.post(
            f"/v1/plugins/{CALCULATOR_PLUGIN_ID}/disable", headers=OWNER_HEADERS
        )
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False

    with TestClient(create_app(settings)) as restarted:
        plugins = restarted.get("/v1/plugins", headers=OWNER_HEADERS).json()
        assert plugins[0]["enabled"] is False
        enabled = restarted.post(
            f"/v1/plugins/{CALCULATOR_PLUGIN_ID}/enable", headers=OWNER_HEADERS
        )
        assert enabled.status_code == 200

    with TestClient(create_app(settings)) as restarted_again:
        plugins = restarted_again.get("/v1/plugins", headers=OWNER_HEADERS).json()
        assert plugins[0]["enabled"] is True


@pytest.mark.parametrize(
    "invalid_state",
    [
        '{"enabled": "private-state-body-do-not-log",',
        '{"version": 2, "enabled": {"private-state-body-do-not-log": true}}',
        '{"version": 1, "enabled": {"private-state-body-do-not-log": "true"}}',
    ],
)
@pytest.mark.parametrize("action", ["enable", "disable"])
def test_corrupt_plugin_state_starts_disabled_and_api_repairs_on_restart(
    settings: Settings, invalid_state: str, action: str
) -> None:
    state_path = settings.runtime_root / "data/plugin-state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(invalid_state, encoding="utf-8")

    with TestClient(create_app(settings)) as recovering:
        plugins = recovering.get("/v1/plugins", headers=OWNER_HEADERS).json()
        assert plugins
        assert all(plugin["enabled"] is False for plugin in plugins)
        entries = recovering.get("/v1/audit", headers=OWNER_HEADERS).json()
        invalid_entry = next(item for item in entries if item["action"] == "plugin.state_invalid")
        assert invalid_entry["outcome"] == "disabled"
        assert invalid_entry["details"] == {
            "reason_code": "saved_plugin_state_unreadable",
            "error_code": "ValidationError",
        }
        assert "private-state-body-do-not-log" not in json.dumps(entries)

        repaired = recovering.post(
            f"/v1/plugins/{CALCULATOR_PLUGIN_ID}/{action}", headers=OWNER_HEADERS
        )
        assert repaired.status_code == 200
        assert repaired.json()["enabled"] is (action == "enable")

    assert json.loads(state_path.read_text(encoding="utf-8")) == {
        "version": 1,
        "enabled": {CALCULATOR_PLUGIN_ID: action == "enable"},
    }
    with TestClient(create_app(settings)) as restarted:
        plugins = restarted.get("/v1/plugins", headers=OWNER_HEADERS).json()
        assert plugins[0]["enabled"] is (action == "enable")
