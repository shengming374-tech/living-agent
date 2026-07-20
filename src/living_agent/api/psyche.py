"""Owner control and inspection API for persistent psyche records."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict

from living_agent.api.dependencies import get_authority, get_psyche_service
from living_agent.api.management import ActorHeader, require_owner
from living_agent.models.psyche import (
    ActivityRecord,
    PsycheState,
    PsycheStateUpdate,
    ThoughtRecord,
    ThoughtRecordCreate,
    UnresolvedTopic,
    UnresolvedTopicCreate,
)
from living_agent.psyche.repository import PsycheNotFoundError
from living_agent.psyche.service import PsycheService, PsycheSourceError
from living_agent.trust.authority import AuthorityResolver

router = APIRouter(prefix="/v1/psyche", tags=["psyche"])


class DecayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    now: datetime | None = None


def _psyche_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PsycheNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, PsycheSourceError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="psyche operation failed")


@router.get("/state", response_model=PsycheState)
async def psyche_state(
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    psyche: Annotated[PsycheService, Depends(get_psyche_service)],
) -> PsycheState:
    require_owner(actor_id, authority)
    return await psyche.state()


@router.patch("/state", response_model=PsycheState)
async def update_psyche_state(
    update: PsycheStateUpdate,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    psyche: Annotated[PsycheService, Depends(get_psyche_service)],
) -> PsycheState:
    require_owner(actor_id, authority)
    return await psyche.update_state(update, actor_id=actor_id)


@router.post("/decay", response_model=PsycheState)
async def decay_psyche(
    request: DecayRequest,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    psyche: Annotated[PsycheService, Depends(get_psyche_service)],
) -> PsycheState:
    require_owner(actor_id, authority)
    return await psyche.decay(actor_id=actor_id, now=request.now)


@router.get("/thoughts", response_model=list[ThoughtRecord])
async def list_thoughts(
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    psyche: Annotated[PsycheService, Depends(get_psyche_service)],
    include_resolved: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ThoughtRecord]:
    require_owner(actor_id, authority)
    return await psyche.thoughts(include_resolved=include_resolved, limit=limit)


@router.post("/thoughts", response_model=ThoughtRecord, status_code=status.HTTP_201_CREATED)
async def create_thought(
    create: ThoughtRecordCreate,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    psyche: Annotated[PsycheService, Depends(get_psyche_service)],
) -> ThoughtRecord:
    require_owner(actor_id, authority)
    try:
        return await psyche.create_thought(create, actor_id=actor_id)
    except (PsycheNotFoundError, PsycheSourceError) as exc:
        raise _psyche_error(exc) from exc


@router.post("/thoughts/{thought_id}/resolve", response_model=ThoughtRecord)
async def resolve_thought(
    thought_id: str,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    psyche: Annotated[PsycheService, Depends(get_psyche_service)],
) -> ThoughtRecord:
    require_owner(actor_id, authority)
    try:
        return await psyche.resolve_thought(thought_id, actor_id=actor_id)
    except PsycheNotFoundError as exc:
        raise _psyche_error(exc) from exc


@router.get("/topics", response_model=list[UnresolvedTopic])
async def list_topics(
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    psyche: Annotated[PsycheService, Depends(get_psyche_service)],
    include_resolved: bool = False,
) -> list[UnresolvedTopic]:
    require_owner(actor_id, authority)
    return await psyche.topics(include_resolved=include_resolved)


@router.post("/topics", response_model=UnresolvedTopic, status_code=status.HTTP_201_CREATED)
async def create_topic(
    create: UnresolvedTopicCreate,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    psyche: Annotated[PsycheService, Depends(get_psyche_service)],
) -> UnresolvedTopic:
    require_owner(actor_id, authority)
    try:
        return await psyche.create_topic(create, actor_id=actor_id)
    except PsycheSourceError as exc:
        raise _psyche_error(exc) from exc


@router.post("/topics/{topic_id}/resolve", response_model=UnresolvedTopic)
async def resolve_topic(
    topic_id: str,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    psyche: Annotated[PsycheService, Depends(get_psyche_service)],
) -> UnresolvedTopic:
    require_owner(actor_id, authority)
    try:
        return await psyche.resolve_topic(topic_id, actor_id=actor_id)
    except PsycheNotFoundError as exc:
        raise _psyche_error(exc) from exc


@router.get("/activities", response_model=list[ActivityRecord])
async def list_activities(
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    psyche: Annotated[PsycheService, Depends(get_psyche_service)],
    limit: int = Query(default=100, ge=1, le=500),
) -> list[ActivityRecord]:
    require_owner(actor_id, authority)
    return await psyche.activities(limit=limit)
