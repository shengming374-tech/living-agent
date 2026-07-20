"""Request-scoped access to host-owned services."""

from fastapi import Request

from living_agent.audit.service import AuditService
from living_agent.runtime.runtime import AgentRuntime
from living_agent.trust.authority import AuthorityResolver


def get_runtime(request: Request) -> AgentRuntime:
    return request.app.state.runtime  # type: ignore[no-any-return]


def get_audit(request: Request) -> AuditService:
    return request.app.state.audit  # type: ignore[no-any-return]


def get_authority(request: Request) -> AuthorityResolver:
    return request.app.state.authority  # type: ignore[no-any-return]
