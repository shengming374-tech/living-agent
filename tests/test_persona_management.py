from pathlib import Path

import yaml
from fastapi.testclient import TestClient

OWNER_HEADERS = {"X-Actor-ID": "owner-1"}


def test_persona_requires_owner_and_rejects_authority_fields(client: TestClient) -> None:
    denied = client.get("/v1/persona/identity", headers={"X-Actor-ID": "member-1"})
    current = client.get("/v1/persona/identity", headers=OWNER_HEADERS)
    payload = yaml.safe_load(current.json()["content"])
    payload["authority"] = "owner"
    invalid = client.post(
        "/v1/persona/identity/stage",
        headers=OWNER_HEADERS,
        json={"expected_version": 1, "content": yaml.safe_dump(payload)},
    )

    assert denied.status_code == 403
    assert current.status_code == 200
    assert invalid.status_code == 422
    assert "forbidden in persona" in invalid.json()["detail"]


def test_persona_stage_test_deploy_history_and_rollback(
    client: TestClient,
) -> None:
    current = client.get("/v1/persona/identity", headers=OWNER_HEADERS).json()
    original_content = current["content"]
    payload = yaml.safe_load(original_content)
    payload["name"] = "LivingAgent Test Persona"
    payload["identity_statement"] = (
        "I am a persistent digital persona made from an artificial intelligence system."
    )
    staged_response = client.post(
        "/v1/persona/identity/stage",
        headers=OWNER_HEADERS,
        json={
            "expected_version": current["version"],
            "content": yaml.safe_dump(payload, sort_keys=False),
        },
    )
    assert staged_response.status_code == 200
    staged = staged_response.json()
    assert "LivingAgent Test Persona" in staged["diff"]
    assert staged["validation"]["passed"]

    premature = client.post(
        f"/v1/persona/stages/{staged['stage_id']}/deploy",
        headers=OWNER_HEADERS,
    )
    assert premature.status_code == 422

    tested = client.post(
        f"/v1/persona/stages/{staged['stage_id']}/test",
        headers=OWNER_HEADERS,
    ).json()
    assert tested["tested"]
    assert len(tested["test_results"]["checked_layers"]) == 6

    deployed = client.post(
        f"/v1/persona/stages/{staged['stage_id']}/deploy",
        headers=OWNER_HEADERS,
    )
    assert deployed.status_code == 200
    deployed_payload = deployed.json()
    assert deployed_payload["artifact"]["version"] == 2
    assert deployed_payload["recovery_version"] == 1
    assert deployed_payload["restart_required"] is True

    persona_root: Path = client.app.state.settings.persona_root
    assert "LivingAgent Test Persona" in (persona_root / "identity.yaml").read_text()
    history = client.get("/v1/persona/identity/history", headers=OWNER_HEADERS).json()
    assert [item["version"] for item in history] == [1, 2]

    rollback = client.post(
        "/v1/persona/identity/rollback",
        headers=OWNER_HEADERS,
        json={"target_version": 1},
    )
    assert rollback.status_code == 200
    assert rollback.json()["artifact"]["version"] == 3
    assert (persona_root / "identity.yaml").read_text() == original_content

    audit = client.get("/v1/audit", headers=OWNER_HEADERS).json()
    actions = {entry["action"] for entry in audit}
    assert {
        "persona.staged",
        "persona.tested",
        "persona.deployed",
        "persona.rolled_back",
    } <= actions


def test_persona_stale_stage_cannot_overwrite_new_deployment(client: TestClient) -> None:
    current = client.get("/v1/persona/traits", headers=OWNER_HEADERS).json()
    first_content = current["content"].replace("warmth: 0.7", "warmth: 0.71")
    second_content = current["content"].replace("warmth: 0.7", "warmth: 0.72")
    first = client.post(
        "/v1/persona/traits/stage",
        headers=OWNER_HEADERS,
        json={"expected_version": 1, "content": first_content},
    ).json()
    second = client.post(
        "/v1/persona/traits/stage",
        headers=OWNER_HEADERS,
        json={"expected_version": 1, "content": second_content},
    ).json()
    for stage in (first, second):
        tested = client.post(
            f"/v1/persona/stages/{stage['stage_id']}/test",
            headers=OWNER_HEADERS,
        )
        assert tested.status_code == 200
    assert (
        client.post(
            f"/v1/persona/stages/{first['stage_id']}/deploy",
            headers=OWNER_HEADERS,
        ).status_code
        == 200
    )
    stale = client.post(
        f"/v1/persona/stages/{second['stage_id']}/deploy",
        headers=OWNER_HEADERS,
    )
    assert stale.status_code == 409
