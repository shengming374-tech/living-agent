"""JSON-RPC schemas for host-to-plugin stdio calls."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PluginCallParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: str
    arguments: dict[str, Any]


class RpcRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"] = "2.0"
    id: str
    method: Literal["invoke"] = "invoke"
    params: PluginCallParams


class RpcError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: int
    message: str


class RpcResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jsonrpc: Literal["2.0"]
    id: str
    result: dict[str, Any] | None = None
    error: RpcError | None = None

    @model_validator(mode="after")
    def require_result_xor_error(self) -> RpcResponse:
        if (self.result is None) == (self.error is None):
            raise ValueError("RPC response must contain exactly one of result or error")
        return self


class PluginInvocationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    operation: str
    output: dict[str, Any]
    taint_labels: set[str] = Field(default_factory=lambda: {"untrusted_plugin_result"})
