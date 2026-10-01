"""Actual ingress bytes are bounded before runtime effects."""

import json

import pytest
from fastapi.testclient import TestClient

from living_agent.app import create_app
from living_agent.config import Settings


@pytest.mark.parametrize("length_header", [None, "1"])
def test_streamed_or_underdeclared_body_is_rejected_without_effects(
    settings: Settings, length_header: str | None
) -> None:
    config = settings.model_copy(update={"ingress_max_request_bytes": 1024})
    raw = json.dumps(
        {
            "content": "hello " * 400,
            "source_type": "direct_message",
            "source_identity": "owner-1",
            "authenticated": True,
        }
    ).encode()
    headers = {"Content-Type": "application/json"}
    if length_header is not None:
        headers["Content-Length"] = length_header
    with TestClient(create_app(config)) as client:
        before = client.get("/v1/audit", headers={"X-Actor-ID": "owner-1"}).json()
        response = client.post("/v1/chat", content=iter([raw[:500], raw[500:]]), headers=headers)
        after = client.get("/v1/audit", headers={"X-Actor-ID": "owner-1"}).json()
        assert response.status_code == 413, response.text
        assert response.json() == {"detail": "request_body_too_large"}
        assert before == after
        assert client.get("/v1/tasks", headers={"X-Actor-ID": "owner-1"}).json() == []


@pytest.mark.parametrize("header", ["bad", "-1"])
def test_invalid_declared_length_is_rejected(settings: Settings, header: str) -> None:
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/chat", content=b"{}", headers={"Content-Length": header})
        assert response.status_code == 400
        assert response.json() == {"detail": "invalid_content_length"}


def test_small_chunked_body_remains_usable(client: TestClient) -> None:
    raw = json.dumps({"content": "hello", "source_type": "direct_message"}).encode()
    response = client.post(
        "/v1/chat",
        content=iter([raw[:20], raw[20:]]),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200


def test_agent_and_adapter_api_bodies_share_limit(settings: Settings) -> None:
    config = settings.model_copy(update={"ingress_max_request_bytes": 1024})
    with TestClient(create_app(config)) as client:
        for path in ("/v1/agent/runs", "/v1/adapters/openclaw/messages"):
            response = client.post(
                path,
                content=iter([b"x" * 600, b"x" * 600]),
                headers={"Content-Type": "application/json", "X-Actor-ID": "owner-1"},
            )
            assert response.status_code == 413, response.text
