"""所有者 Agent 控制接口。 / Owner-only agent goal control API."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from living_agent.agent.contracts import AgentResumeRequest, AgentRun, AgentStartRequest
from living_agent.agent.repository import AgentConflictError, AgentNotFoundError
from living_agent.agent.service import AgentService
from living_agent.api.dependencies import get_authority
from living_agent.api.management import ActorHeader, require_owner
from living_agent.execution.tool_catalog import TOOL_CATALOG
from living_agent.models.events import IngressEnvelope, SourceType
from living_agent.trust.authority import AuthorityResolver
from living_agent.trust.boundary import TrustBoundary

router = APIRouter(prefix="/v1/agent", tags=["agent"])


def get_agent(request: Request) -> AgentService:
    return request.app.state.agent_service  # type: ignore[no-any-return]


AgentDep = Annotated[AgentService, Depends(get_agent)]
AuthorityDep = Annotated[AuthorityResolver, Depends(get_authority)]


def agent_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AgentNotFoundError):
        return HTTPException(404, "agent run not found")
    if isinstance(exc, AgentConflictError):
        return HTTPException(409, str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(403, "agent operation denied")
    return HTTPException(400, "invalid agent request")


@router.get("/tools")
async def tools(actor_id: ActorHeader, authority: AuthorityDep) -> list[dict[str, object]]:
    require_owner(actor_id, authority)
    return [spec.declaration() for spec in TOOL_CATALOG.values()]


@router.get("/runs", response_model=list[AgentRun])
async def runs(
    actor_id: ActorHeader,
    authority: AuthorityDep,
    agent: AgentDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AgentRun]:
    require_owner(actor_id, authority)
    return await agent.repository.list_runs(limit)


@router.post("/runs", response_model=AgentRun)
async def start(
    body: AgentStartRequest,
    actor_id: ActorHeader,
    authority: AuthorityDep,
    agent: AgentDep,
    request: Request,
) -> AgentRun:
    require_owner(actor_id, authority)
    event = TrustBoundary(authority).normalize(
        IngressEnvelope(
            content=body.goal,
            source_type=SourceType.DIRECT_MESSAGE,
            source_identity=actor_id,
            conversation_id=body.conversation_id,
            authenticated=True,
        )
    )
    try:
        agent.authorize(event)
        await request.app.state.event_repository.add(event)
        return await agent.start(event, body.goal)
    except (ValueError, PermissionError) as exc:
        raise agent_error(exc) from exc


@router.get("/runs/{run_id}", response_model=AgentRun)
async def get(
    run_id: str, actor_id: ActorHeader, authority: AuthorityDep, agent: AgentDep
) -> AgentRun:
    require_owner(actor_id, authority)
    try:
        return await agent.repository.get(run_id)
    except AgentNotFoundError as exc:
        raise agent_error(exc) from exc


@router.post("/runs/{run_id}/resume", response_model=AgentRun)
async def resume(
    run_id: str,
    body: AgentResumeRequest,
    actor_id: ActorHeader,
    authority: AuthorityDep,
    agent: AgentDep,
) -> AgentRun:
    require_owner(actor_id, authority)
    try:
        return await agent.resume(run_id, actor_id=actor_id, message=body.message)
    except (ValueError, LookupError, PermissionError) as exc:
        raise agent_error(exc) from exc


@router.post("/runs/{run_id}/confirm", response_model=AgentRun)
async def confirm(
    run_id: str, actor_id: ActorHeader, authority: AuthorityDep, agent: AgentDep
) -> AgentRun:
    require_owner(actor_id, authority)
    try:
        return await agent.resume(run_id, actor_id=actor_id, confirm=True)
    except (ValueError, LookupError, PermissionError) as exc:
        raise agent_error(exc) from exc


@router.post("/runs/{run_id}/cancel", response_model=AgentRun)
async def cancel(
    run_id: str, actor_id: ActorHeader, authority: AuthorityDep, agent: AgentDep
) -> AgentRun:
    require_owner(actor_id, authority)
    try:
        return await agent.cancel(run_id, actor_id=actor_id)
    except (ValueError, LookupError, PermissionError) as exc:
        raise agent_error(exc) from exc
