"""Owner-only room APIs / 仅限所有者的群聊接口。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from living_agent.api.dependencies import get_authority
from living_agent.api.management import ActorHeader, require_owner
from living_agent.groups.models import Room, RoomCreate, SendMessage
from living_agent.groups.repository import RoomConflictError
from living_agent.groups.service import GroupService
from living_agent.trust.authority import AuthorityResolver

router = APIRouter(prefix="/v1/groups", tags=["groups"])
AuthorityDep = Annotated[AuthorityResolver, Depends(get_authority)]


def get_groups(request: Request) -> GroupService:
    return request.app.state.group_service  # type: ignore[no-any-return]


GroupsDep = Annotated[GroupService, Depends(get_groups)]


@router.get("", response_model=list[Room])
async def list_rooms(
    actor_id: ActorHeader, authority: AuthorityDep, groups: GroupsDep
) -> list[Room]:
    require_owner(actor_id, authority)
    return await groups.repository.list_rooms()


@router.post("", response_model=Room)
async def create(
    body: RoomCreate, actor_id: ActorHeader, authority: AuthorityDep, groups: GroupsDep
) -> Room:
    require_owner(actor_id, authority)
    try:
        return await groups.create(body, actor_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/{room_id}", response_model=Room)
async def get(
    room_id: str, actor_id: ActorHeader, authority: AuthorityDep, groups: GroupsDep
) -> Room:
    require_owner(actor_id, authority)
    try:
        return await groups.repository.get(room_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{room_id}/messages", response_model=Room)
async def send(
    room_id: str,
    body: SendMessage,
    actor_id: ActorHeader,
    authority: AuthorityDep,
    groups: GroupsDep,
) -> Room:
    require_owner(actor_id, authority)
    try:
        return await groups.send(room_id, body, actor_id)
    except RoomConflictError as exc:
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/{room_id}/stop", response_model=Room)
async def stop(
    room_id: str, actor_id: ActorHeader, authority: AuthorityDep, groups: GroupsDep
) -> Room:
    require_owner(actor_id, authority)
    try:
        return await groups.stop(room_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
