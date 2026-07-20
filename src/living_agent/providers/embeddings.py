"""Audited embedding providers with strict OpenAI-compatible HTTP validation."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from typing import Annotated, Any, Literal, Protocol

import httpx2
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    ValidationError,
    field_validator,
)

from living_agent.audit.service import AuditService
from living_agent.execution.broker import CapabilityBroker
from living_agent.models.capabilities import (
    CapabilityGrant,
    CapabilityRequest,
    DecisionOutcome,
)

EMBEDDING_CAPABILITY = "model.embedding.generate"
_ALLOW_OUTCOMES = {
    DecisionOutcome.ALLOW,
    DecisionOutcome.ALLOW_ONCE,
    DecisionOutcome.ALLOW_WITH_REDACTION,
}
_FEATURE_PATTERN = re.compile(r"\w+", re.UNICODE)
EmbeddingText = Annotated[str, StringConstraints(min_length=1, max_length=100000)]


class EmbeddingProviderError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class EmbeddingLimitError(ValueError):
    pass


class EmbeddingPermissionError(PermissionError):
    pass


class EmbeddingUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class EmbeddingVector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    embedding: list[float] = Field(min_length=1, max_length=65536)

    @field_validator("embedding")
    @classmethod
    def finite_vector(cls, value: list[float]) -> list[float]:
        if not all(math.isfinite(component) for component in value):
            raise ValueError("embedding components must be finite")
        return value


class EmbeddingResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object: Literal["list"] = "list"
    data: list[EmbeddingVector] = Field(min_length=1, max_length=256)
    model: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=255)
    dimensions: int = Field(ge=1, le=65536)
    usage: EmbeddingUsage = Field(default_factory=EmbeddingUsage)


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: list[EmbeddingText] = Field(min_length=1, max_length=256)

    @field_validator("input")
    @classmethod
    def validate_input(cls, value: list[str]) -> list[str]:
        if any(not item.strip() for item in value):
            raise ValueError("embedding input cannot contain empty text")
        return value


class EmbeddingStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=255)
    configured: bool
    remote: bool
    dimensions: int | None
    max_batch_size: int
    max_input_chars: int
    max_total_chars: int


class EmbeddingCapabilityArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=255)
    input_count: int = Field(ge=1, le=256)
    total_chars: int = Field(ge=1, le=1000000)


class EmbeddingProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    @property
    def dimensions(self) -> int | None: ...

    @property
    def remote(self) -> bool: ...

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult: ...

    async def close(self) -> None: ...


class MockEmbeddingProvider:
    """Deterministic normalized feature hashing for tests and local development."""

    name = "mock"
    remote = False

    def __init__(self, *, model: str = "mock-hash-v1", dimensions: int = 32) -> None:
        self.model = model
        self.dimensions = dimensions

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        data = [
            EmbeddingVector(index=index, embedding=self._vector(text))
            for index, text in enumerate(texts)
        ]
        return EmbeddingResult(
            data=data,
            model=self.model,
            provider=self.name,
            dimensions=self.dimensions,
        )

    async def close(self) -> None:
        return None

    def _vector(self, text: str) -> list[float]:
        normalized = " ".join(text.casefold().split())
        features = _FEATURE_PATTERN.findall(normalized)
        features.extend(
            normalized[index : index + 3] for index in range(max(0, len(normalized) - 2))
        )
        values = [0.0] * self.dimensions
        for feature in features or [normalized]:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            values[bucket] += sign
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0.0:
            values[0] = 1.0
            return values
        return [value / norm for value in values]


class _UpstreamEmbeddingItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int = Field(ge=0)
    embedding: list[float] = Field(min_length=1, max_length=65536)


class _UpstreamUsage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class _UpstreamResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: list[_UpstreamEmbeddingItem] = Field(min_length=1, max_length=256)
    model: str | None = Field(default=None, min_length=1, max_length=255)
    usage: _UpstreamUsage | None = None


class OpenAICompatibleEmbeddingProvider:
    name = "openai_compatible"
    remote = True

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr | None,
        model: str,
        dimensions: int | None,
        timeout_seconds: float,
        max_response_bytes: int,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.dimensions = dimensions
        self._endpoint = f"{base_url.rstrip('/')}/embeddings"
        self._api_key = api_key.get_secret_value() if api_key is not None else None
        self._max_response_bytes = max_response_bytes
        self._client = client or httpx2.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )
        self._owns_client = client is None

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        payload: dict[str, Any] = {"model": self.model, "input": list(texts)}
        if self.dimensions is not None:
            payload["dimensions"] = self.dimensions
        headers = {"accept": "application/json", "content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        try:
            async with self._client.stream(
                "POST",
                self._endpoint,
                json=payload,
                headers=headers,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise EmbeddingProviderError(f"provider_http_{response.status_code}")
                raw = await self._bounded_body(response)
        except EmbeddingProviderError:
            raise
        except httpx2.TimeoutException as exc:
            raise EmbeddingProviderError("provider_timeout") from exc
        except httpx2.TransportError as exc:
            raise EmbeddingProviderError("provider_unavailable") from exc
        try:
            decoded = json.loads(raw)
            upstream = _UpstreamResponse.model_validate(decoded)
            return self._validated_result(upstream, expected_count=len(texts))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError) as exc:
            raise EmbeddingProviderError("provider_response_invalid") from exc

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _bounded_body(self, response: httpx2.Response) -> bytes:
        length = response.headers.get("content-length")
        if length is not None:
            try:
                if int(length) > self._max_response_bytes:
                    raise EmbeddingProviderError("provider_response_too_large")
            except ValueError as exc:
                raise EmbeddingProviderError("provider_response_invalid") from exc
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > self._max_response_bytes:
                raise EmbeddingProviderError("provider_response_too_large")
        return bytes(body)

    def _validated_result(
        self,
        upstream: _UpstreamResponse,
        *,
        expected_count: int,
    ) -> EmbeddingResult:
        ordered = sorted(upstream.data, key=lambda item: item.index)
        if [item.index for item in ordered] != list(range(expected_count)):
            raise ValueError("embedding indexes do not match input")
        dimensions = len(ordered[0].embedding)
        if self.dimensions is not None and dimensions != self.dimensions:
            raise ValueError("embedding dimensions do not match configuration")
        if any(len(item.embedding) != dimensions for item in ordered):
            raise ValueError("embedding dimensions are inconsistent")
        data = [EmbeddingVector(index=item.index, embedding=item.embedding) for item in ordered]
        usage = (
            EmbeddingUsage.model_validate(upstream.usage.model_dump())
            if upstream.usage
            else EmbeddingUsage()
        )
        return EmbeddingResult(
            data=data,
            model=upstream.model or self.model,
            provider=self.name,
            dimensions=dimensions,
            usage=usage,
        )


class EmbeddingService:
    def __init__(
        self,
        *,
        provider: EmbeddingProvider,
        broker: CapabilityBroker,
        audit: AuditService,
        max_batch_size: int,
        max_input_chars: int,
        max_total_chars: int,
    ) -> None:
        self._provider = provider
        self._broker = broker
        self._audit = audit
        self._max_batch_size = max_batch_size
        self._max_input_chars = max_input_chars
        self._max_total_chars = max_total_chars

    def status(self) -> EmbeddingStatus:
        return EmbeddingStatus(
            provider=self._provider.name,
            model=self._provider.model,
            configured=True,
            remote=self._provider.remote,
            dimensions=self._provider.dimensions,
            max_batch_size=self._max_batch_size,
            max_input_chars=self._max_input_chars,
            max_total_chars=self._max_total_chars,
        )

    async def generate(self, texts: Sequence[str], *, actor_id: str) -> EmbeddingResult:
        normalized = list(texts)
        total_chars = self._validate_limits(normalized)
        scope = f"embedding:{self._provider.name}:{self._provider.model}"
        grant = CapabilityGrant(
            actor_id=actor_id,
            capability=EMBEDDING_CAPABILITY,
            operations={"send"},
            resource_scopes={scope},
            one_time=True,
        )
        self._broker.add_grant(grant)
        decision = await self._broker.decide(
            CapabilityRequest(
                actor_id=actor_id,
                capability=EMBEDDING_CAPABILITY,
                operation="send",
                resource_scope=scope,
                arguments={
                    "provider": self._provider.name,
                    "model": self._provider.model,
                    "input_count": len(normalized),
                    "total_chars": total_chars,
                },
                source_event_ids=[],
                reason="Owner requested embeddings for an explicit text batch.",
            ),
            confirmed_by=actor_id,
        )
        if decision.outcome not in _ALLOW_OUTCOMES:
            self._broker.revoke_grant(grant)
            raise EmbeddingPermissionError(decision.reason_code)
        try:
            result = await self._provider.embed(normalized)
        except EmbeddingProviderError as exc:
            await self._audit_failure(
                actor_id=actor_id,
                input_count=len(normalized),
                total_chars=total_chars,
                error_code=exc.code,
            )
            raise
        try:
            self._validate_result(result, expected_count=len(normalized))
        except ValueError as exc:
            error = EmbeddingProviderError("provider_response_invalid")
            await self._audit_failure(
                actor_id=actor_id,
                input_count=len(normalized),
                total_chars=total_chars,
                error_code=error.code,
            )
            raise error from exc
        await self._audit.append(
            action="embedding.generated",
            actor_id=actor_id,
            outcome="success",
            details=self._audit_details(
                input_count=len(normalized),
                total_chars=total_chars,
                dimensions=result.dimensions,
            ),
        )
        return result

    async def close(self) -> None:
        await self._provider.close()

    def _validate_limits(self, texts: list[str]) -> int:
        if not texts or any(not text.strip() for text in texts):
            raise EmbeddingLimitError("embedding input cannot be empty")
        if len(texts) > self._max_batch_size:
            raise EmbeddingLimitError("embedding batch exceeds configured limit")
        if any(len(text) > self._max_input_chars for text in texts):
            raise EmbeddingLimitError("embedding input exceeds configured character limit")
        total_chars = sum(len(text) for text in texts)
        if total_chars > self._max_total_chars:
            raise EmbeddingLimitError("embedding batch exceeds total character limit")
        return total_chars

    def _audit_details(self, **details: Any) -> dict[str, Any]:
        return {
            "provider": self._provider.name,
            "model": self._provider.model,
            **details,
        }

    async def _audit_failure(
        self,
        *,
        actor_id: str,
        input_count: int,
        total_chars: int,
        error_code: str,
    ) -> None:
        await self._audit.append(
            action="embedding.generated",
            actor_id=actor_id,
            outcome="failure",
            details=self._audit_details(
                input_count=input_count,
                total_chars=total_chars,
                error_code=error_code,
            ),
        )

    @staticmethod
    def _validate_result(result: EmbeddingResult, *, expected_count: int) -> None:
        if len(result.data) != expected_count:
            raise ValueError("embedding count does not match input")
        if [item.index for item in result.data] != list(range(expected_count)):
            raise ValueError("embedding indexes do not match input")
        if any(len(item.embedding) != result.dimensions for item in result.data):
            raise ValueError("embedding dimensions do not match result metadata")
