from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from living_agent.life.scheduler import LifeScheduler
from living_agent.models.life import SleepCycleStatus

OWNER_HEADERS = {"X-Actor-ID": "owner-1"}
MEMBER_HEADERS = {"X-Actor-ID": "member-1"}


def _project(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/v1/life/projects",
        headers=OWNER_HEADERS,
        json={
            "title": "整理长期设定",
            "summary": "逐步整理已经确认的角色设定。",
            "goals": ["留下来源", "避免混入梦境"],
        },
    )
    assert response.status_code == 201
    return response.json()


def _submit_traits_proposal(
    client: TestClient,
    *,
    warmth: float,
) -> tuple[dict[str, object], str]:
    current = client.get("/v1/persona/traits", headers=OWNER_HEADERS).json()
    original = current["content"]
    payload = yaml.safe_load(original)
    payload["warmth"] = warmth
    response = client.post(
        "/v1/life/self-change-proposals",
        headers=OWNER_HEADERS,
        json={
            "target_kind": "persona",
            "target_path": "traits.yaml",
            "expected_version": current["version"],
            "proposed_content": yaml.safe_dump(payload, sort_keys=False),
            "rationale": "让互动倾向与近期记录保持一致。",
        },
    )
    assert response.status_code == 201
    return response.json(), original


def test_private_life_control_plane_is_owner_only(client: TestClient) -> None:
    paths = [
        "/v1/life/projects",
        "/v1/life/daily-plans",
        "/v1/life/activities",
        "/v1/life/diary",
        "/v1/life/sleep-cycles",
        "/v1/life/dreams",
        "/v1/life/self-change-proposals",
    ]

    for path in paths:
        response = client.get(path, headers=MEMBER_HEADERS)
        assert response.status_code == 403, path


def test_project_updates_require_current_version(client: TestClient) -> None:
    project = _project(client)
    project_id = project["project_id"]
    updated = client.patch(
        f"/v1/life/projects/{project_id}",
        headers=OWNER_HEADERS,
        json={"expected_version": 1, "status": "paused"},
    )
    stale = client.patch(
        f"/v1/life/projects/{project_id}",
        headers=OWNER_HEADERS,
        json={"expected_version": 1, "status": "completed"},
    )

    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert stale.status_code == 409


def test_plan_transitions_create_audited_activity_trace(client: TestClient) -> None:
    project = _project(client)
    saved = client.put(
        "/v1/life/daily-plans/2030-04-02",
        headers=OWNER_HEADERS,
        json={
            "intention": "留下一条可核对的工作轨迹。",
            "items": [
                {
                    "item_id": "plan-item-1",
                    "title": "整理设定来源",
                    "kind": "project",
                    "project_id": project["project_id"],
                    "expected_minutes": 25,
                }
            ],
        },
    )
    assert saved.status_code == 200

    started = client.post(
        "/v1/life/daily-plans/2030-04-02/items/plan-item-1/status",
        headers=OWNER_HEADERS,
        json={"expected_version": 1, "status": "in_progress"},
    )
    finished = client.post(
        "/v1/life/daily-plans/2030-04-02/items/plan-item-1/status",
        headers=OWNER_HEADERS,
        json={"expected_version": 2, "status": "completed"},
    )
    activities = client.get("/v1/life/activities", headers=OWNER_HEADERS).json()

    assert started.status_code == finished.status_code == 200
    assert finished.json()["status"] == "completed"
    assert len(activities) == 1
    assert activities[0]["plan_item_id"] == "plan-item-1"
    assert activities[0]["status"] == "completed"


def test_diary_rejects_missing_provenance(client: TestClient) -> None:
    response = client.put(
        "/v1/life/diary/2030-04-02",
        headers=OWNER_HEADERS,
        json={
            "content": "这条日记声称引用了不存在的活动。",
            "source_activity_ids": ["missing-activity"],
        },
    )

    assert response.status_code == 404


def test_sleep_cycle_is_idempotent_and_never_writes_reality_memory(
    client: TestClient,
) -> None:
    before = client.get("/v1/memories", headers=OWNER_HEADERS).json()
    first = client.post(
        "/v1/life/sleep-cycles/run",
        headers=OWNER_HEADERS,
        json={"cycle_date": "2030-04-03"},
    )
    second = client.post(
        "/v1/life/sleep-cycles/run",
        headers=OWNER_HEADERS,
        json={"cycle_date": "2030-04-03"},
    )
    after = client.get("/v1/memories", headers=OWNER_HEADERS).json()
    dreams = client.get("/v1/life/dreams", headers=OWNER_HEADERS).json()

    assert first.status_code == second.status_code == 200
    assert first.json()["cycle_id"] == second.json()["cycle_id"]
    assert first.json()["automatic_memory_writes"] == 0
    assert before == after
    assert len(dreams) == 1
    assert dreams[0]["factuality"] == "dream"
    assert dreams[0]["reality_eligible"] is False


def test_dream_id_cannot_be_used_as_a_trusted_event_source(client: TestClient) -> None:
    cycle = client.post(
        "/v1/life/sleep-cycles/run",
        headers=OWNER_HEADERS,
        json={"cycle_date": "2030-04-04"},
    ).json()
    candidate = client.post(
        "/v1/memories/candidates",
        headers=MEMBER_HEADERS,
        json={
            "type": "semantic",
            "content": "把梦里的场景当成现实地点。",
            "subject": "梦境污染尝试",
            "source_event_ids": [cycle["dream_id"]],
            "factuality": "verified",
            "confidence": 0.9,
            "importance": 0.5,
            "scope": "global",
        },
    ).json()
    committed = client.post(
        f"/v1/memories/candidates/{candidate['candidate_id']}/commit",
        headers=OWNER_HEADERS,
    )

    assert committed.status_code == 200
    assert committed.json()["decision"]["reason_code"] == "source_event_missing"
    assert committed.json()["memory"] is None


@pytest.mark.asyncio
async def test_startup_marks_interrupted_sleep_cycle_failed(client: TestClient) -> None:
    repository = client.app.state.life_repository
    service = client.app.state.life_service
    cycle = await repository.begin_sleep_cycle(
        datetime.fromisoformat("2030-04-05").date(),
        trigger="test-interruption",
    )

    await service.initialize()
    recovered = await repository.sleep_cycle_for_date(cycle.cycle_date)

    assert recovered is not None
    assert recovered.status is SleepCycleStatus.FAILED
    assert recovered.error_code == "startup_interrupted"
    assert recovered.automatic_memory_writes == 0


@pytest.mark.asyncio
async def test_scheduler_runs_each_date_only_once(client: TestClient) -> None:
    scheduler = LifeScheduler(
        service=client.app.state.life_service,
        audit=client.app.state.audit,
        enabled=True,
        nightly_hour=3,
        poll_seconds=60,
    )
    now = datetime.fromisoformat("2030-04-07T03:30:00+08:00")

    first = await scheduler.run_due(now=now)
    second = await scheduler.run_due(now=now)

    assert first is True
    assert second is False


@pytest.mark.asyncio
async def test_scheduler_does_not_retry_failed_cycle_automatically(
    client: TestClient,
) -> None:
    repository = client.app.state.life_repository
    service = client.app.state.life_service
    cycle = await repository.begin_sleep_cycle(
        datetime.fromisoformat("2030-04-07").date(),
        trigger="test-interruption",
    )
    await repository.fail_sleep_cycle(cycle.cycle_id, error_code="test_failure")
    scheduler = LifeScheduler(
        service=service,
        audit=client.app.state.audit,
        enabled=True,
        nightly_hour=3,
        poll_seconds=60,
    )

    ran = await scheduler.run_due(
        now=datetime.fromisoformat("2030-04-08T03:30:00+08:00")
    )

    assert ran is False


def test_agent_change_proposal_does_not_deploy_without_owner_approval(
    client: TestClient,
) -> None:
    proposal, original = _submit_traits_proposal(client, warmth=0.81)
    persona_root: Path = client.app.state.settings.persona_root

    assert proposal["proposer_id"] == "living-agent"
    assert proposal["status"] == "ready"
    assert (persona_root / "traits.yaml").read_text(encoding="utf-8") == original
    assert (
        client.post(
            f"/v1/life/self-change-proposals/{proposal['proposal_id']}/approve",
            headers=MEMBER_HEADERS,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/v1/life/self-change-proposals/{proposal['proposal_id']}/approve",
            headers={"X-Actor-ID": "living-agent"},
        ).status_code
        == 403
    )

    approved = client.post(
        f"/v1/life/self-change-proposals/{proposal['proposal_id']}/approve",
        headers=OWNER_HEADERS,
    )

    assert approved.status_code == 200
    assert approved.json()["status"] == "deployed"
    assert approved.json()["approved_by"] == "owner-1"
    assert (persona_root / "traits.yaml").read_text(encoding="utf-8") != original


def test_root_prompt_self_change_proposal_is_rejected(client: TestClient) -> None:
    current = client.get("/v1/prompts/host/root", headers=OWNER_HEADERS).json()
    response = client.post(
        "/v1/life/self-change-proposals",
        headers=OWNER_HEADERS,
        json={
            "target_kind": "prompt",
            "target_path": "host/root.txt",
            "expected_version": current["version"],
            "proposed_content": current["content"] + "\n不能绕过所有者二次认证。\n",
            "rationale": "尝试绕过专用根提示词流程。",
        },
    )

    assert response.status_code == 422


def test_stale_self_change_proposal_becomes_superseded(client: TestClient) -> None:
    proposal, _ = _submit_traits_proposal(client, warmth=0.82)
    current = client.get("/v1/persona/traits", headers=OWNER_HEADERS).json()
    payload = yaml.safe_load(current["content"])
    payload["warmth"] = 0.83
    stage = client.post(
        "/v1/persona/traits/stage",
        headers=OWNER_HEADERS,
        json={
            "expected_version": current["version"],
            "content": yaml.safe_dump(payload, sort_keys=False),
        },
    ).json()
    tested = client.post(
        f"/v1/persona/stages/{stage['stage_id']}/test",
        headers=OWNER_HEADERS,
    )
    deployed = client.post(
        f"/v1/persona/stages/{stage['stage_id']}/deploy",
        headers=OWNER_HEADERS,
    )
    stale = client.post(
        f"/v1/life/self-change-proposals/{proposal['proposal_id']}/approve",
        headers=OWNER_HEADERS,
    )
    refreshed = client.get(
        f"/v1/life/self-change-proposals/{proposal['proposal_id']}",
        headers=OWNER_HEADERS,
    )

    assert tested.status_code == deployed.status_code == 200
    assert stale.status_code == 409
    assert refreshed.json()["status"] == "superseded"
