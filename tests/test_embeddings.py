from __future__ import annotations

import json
import math
from collections.abc import Iterator, Sequence
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from living_agent.app import create_app
from living_agent.config import Settings
from living_agent.providers.embeddings import (
    EmbeddingProviderError,
    EmbeddingResult,
    EmbeddingVector,
    OpenAICompatibleEmbeddingProvider,
)

OWNER_HEADERS = {"X-Actor-ID": "owner-1"}
API_KEY = "embedding-provider-test-key"


def test_embedding_configuration_validates_remote_transport() -> None:
    with pytest.raises(ValidationError, match="embedding_api_base_url is required"):
        Settings(
            embedding_provider="openai_compatible",
            embedding_api_base_url=None,
        )
    with pytest.raises(ValidationError, match="requires HTTPS"):
        Settings(
            embedding_provider="openai_compatible",
            embedding_api_base_url="http://embedding.example/v1",
        )
    with pytest.raises(ValidationError, match="cannot contain credentials"):
        Settings(
            embedding_provider="openai_compatible",
            embedding_api_base_url="https://user:password@embedding.example/v1",
        )

    local = Settings(
        embedding_provider="openai_compatible",
        embedding_api_base_url="http://127.0.0.1:11434/v1",
    )
    assert local.embedding_api_base_url == "http://127.0.0.1:11434/v1"


def test_mock_embedding_api_is_owner_only_deterministic_and_audited(
    client: TestClient,
) -> None:
    denied = client.get("/v1/embeddings/status", headers={"X-Actor-ID": "member-1"})
    status_response = client.get("/v1/embeddings/status", headers=OWNER_HEADERS)
    generated = client.post(
        "/v1/embeddings",
        headers=OWNER_HEADERS,
        json={"input": ["jasmine tea", "jasmine tea", "project deadline"]},
    )

    assert denied.status_code == 403
    assert status_response.status_code == 200
    assert status_response.json() == {
        "provider": "mock",
        "model": "mock-hash-v1",
        "configured": True,
        "remote": False,
        "dimensions": 32,
        "max_batch_size": 32,
        "max_input_chars": 12000,
        "max_total_chars": 48000,
    }
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["provider"] == "mock"
    assert payload["dimensions"] == 32
    assert len(payload["data"]) == 3
    first = payload["data"][0]["embedding"]
    assert first == payload["data"][1]["embedding"]
    assert first != payload["data"][2]["embedding"]
    assert math.isclose(sum(value * value for value in first), 1.0)

    audit = client.get("/v1/audit?limit=100", headers=OWNER_HEADERS).json()
    generated_audit = next(entry for entry in audit if entry["action"] == "embedding.generated")
    assert generated_audit["outcome"] == "success"
    assert generated_audit["details"] == {
        "provider": "mock",
        "model": "mock-hash-v1",
        "input_count": 3,
        "total_chars": 38,
        "dimensions": 32,
    }
    assert "jasmine tea" not in repr(generated_audit)
    assert any(
        entry["action"] == "capability.decision"
        and entry["outcome"] == "ALLOW_ONCE"
        and entry["details"]["capability"] == "model.embedding.generate"
        for entry in audit
    )
    assert any(entry["action"] == "user.confirmation" for entry in audit)


def test_embedding_api_enforces_runtime_limits_and_strict_schema(
    settings: Settings,
) -> None:
    configured = settings.model_copy(
        update={
            "embedding_max_batch_size": 2,
            "embedding_max_input_chars": 5,
            "embedding_max_total_chars": 8,
        }
    )
    with TestClient(create_app(configured)) as test_client:
        too_many = test_client.post(
            "/v1/embeddings",
            headers=OWNER_HEADERS,
            json={"input": ["one", "two", "three"]},
        )
        too_long = test_client.post(
            "/v1/embeddings",
            headers=OWNER_HEADERS,
            json={"input": ["123456"]},
        )
        total_too_long = test_client.post(
            "/v1/embeddings",
            headers=OWNER_HEADERS,
            json={"input": ["12345", "6789"]},
        )
        unknown = test_client.post(
            "/v1/embeddings",
            headers=OWNER_HEADERS,
            json={"input": ["valid"], "model": "unauthorized-model"},
        )

    assert too_many.status_code == 422
    assert too_long.status_code == 422
    assert total_too_long.status_code == 422
    assert unknown.status_code == 422


async def test_openai_compatible_provider_sends_expected_contract() -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == "https://embedding.example/v1/embeddings"
        assert request.headers["authorization"] == f"Bearer {API_KEY}"
        assert json.loads(request.content) == {
            "model": "embed-model",
            "input": ["first", "second"],
            "dimensions": 3,
        }
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0.0, 1.0, 0.0]},
                    {"object": "embedding", "index": 0, "embedding": [1.0, 0.0, 0.0]},
                ],
                "model": "embed-model",
                "usage": {"prompt_tokens": 2, "total_tokens": 2},
            },
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        provider = OpenAICompatibleEmbeddingProvider(
            base_url="https://embedding.example/v1",
            api_key=SecretStr(API_KEY),
            model="embed-model",
            dimensions=3,
            timeout_seconds=2.0,
            max_response_bytes=4096,
            client=client,
        )
        result = await provider.embed(["first", "second"])

    assert result.data[0].embedding == [1.0, 0.0, 0.0]
    assert result.data[1].embedding == [0.0, 1.0, 0.0]
    assert result.usage.total_tokens == 2


@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        (httpx2.Response(401, text=f"invalid key {API_KEY}"), "provider_http_401"),
        (httpx2.Response(200, text="not-json"), "provider_response_invalid"),
        (
            httpx2.Response(
                200,
                json={
                    "data": [
                        {"index": 0, "embedding": [1.0, 0.0]},
                        {"index": 1, "embedding": [1.0, 0.0, 0.0]},
                    ]
                },
            ),
            "provider_response_invalid",
        ),
        (
            httpx2.Response(200, content=b"x" * 2048),
            "provider_response_too_large",
        ),
    ],
)
async def test_openai_compatible_provider_normalizes_untrusted_failures(
    response: httpx2.Response,
    error_code: str,
) -> None:
    async def handler(_request: httpx2.Request) -> httpx2.Response:
        return response

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        provider = OpenAICompatibleEmbeddingProvider(
            base_url="https://embedding.example/v1",
            api_key=SecretStr(API_KEY),
            model="embed-model",
            dimensions=None,
            timeout_seconds=2.0,
            max_response_bytes=1024,
            client=client,
        )
        with pytest.raises(EmbeddingProviderError) as raised:
            await provider.embed(["secret input", "other input"])

    assert raised.value.code == error_code
    assert str(raised.value) == error_code
    assert API_KEY not in repr(raised.value)


async def test_openai_compatible_provider_normalizes_timeout() -> None:
    async def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("upstream details", request=request)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        provider = OpenAICompatibleEmbeddingProvider(
            base_url="https://embedding.example/v1",
            api_key=SecretStr(API_KEY),
            model="embed-model",
            dimensions=None,
            timeout_seconds=2.0,
            max_response_bytes=1024,
            client=client,
        )
        with pytest.raises(EmbeddingProviderError, match="provider_timeout"):
            await provider.embed(["input"])


class _FailingProvider:
    name = "openai_compatible"
    model = "failing-model"
    dimensions = 3
    remote = True

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        del texts
        raise EmbeddingProviderError("provider_unavailable")

    async def close(self) -> None:
        return None


class _WrongShapeProvider:
    name = "openai_compatible"
    model = "wrong-shape-model"
    dimensions = 3
    remote = True

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        del texts
        return EmbeddingResult(
            data=[EmbeddingVector(index=0, embedding=[1.0, 0.0, 0.0])],
            model=self.model,
            provider=self.name,
            dimensions=self.dimensions,
        )

    async def close(self) -> None:
        return None


@pytest.fixture
def failing_provider_client(
    settings: Settings,
    tmp_path: Path,
) -> Iterator[TestClient]:
    configured = settings.model_copy(
        update={"database_url": f"sqlite+aiosqlite:///{tmp_path / 'embedding-failure.db'}"}
    )
    with TestClient(create_app(configured, embedding_provider=_FailingProvider())) as test_client:
        yield test_client


def test_provider_failure_is_generic_and_audited_without_input(
    failing_provider_client: TestClient,
) -> None:
    phrase = "private material must not enter audit"
    response = failing_provider_client.post(
        "/v1/embeddings",
        headers=OWNER_HEADERS,
        json={"input": [phrase]},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "embedding provider request failed"}
    audit = failing_provider_client.get("/v1/audit?limit=100", headers=OWNER_HEADERS).json()
    failure = next(entry for entry in audit if entry["action"] == "embedding.generated")
    assert failure["outcome"] == "failure"
    assert failure["details"]["error_code"] == "provider_unavailable"
    assert phrase not in repr(audit)


def test_service_rejects_wrong_shape_from_custom_provider(settings: Settings) -> None:
    with TestClient(create_app(settings, embedding_provider=_WrongShapeProvider())) as test_client:
        response = test_client.post(
            "/v1/embeddings",
            headers=OWNER_HEADERS,
            json={"input": ["first", "second"]},
        )
        audit = test_client.get("/v1/audit?limit=100", headers=OWNER_HEADERS).json()

    assert response.status_code == 502
    failure = next(entry for entry in audit if entry["action"] == "embedding.generated")
    assert failure["details"]["error_code"] == "provider_response_invalid"
