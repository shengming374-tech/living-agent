"""Owner-only inspection API for automatically registered users."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from living_agent.api.dependencies import get_authority, get_user_service
from living_agent.api.management import ActorHeader, require_owner
from living_agent.models.users import UserProfile
from living_agent.trust.authority import AuthorityResolver
from living_agent.users.repository import UserNotFoundError
from living_agent.users.service import UserService

router = APIRouter(prefix="/v1/users", tags=["users"])


@router.get("", response_model=list[UserProfile])
async def list_users(
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    users: Annotated[UserService, Depends(get_user_service)],
    query: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[UserProfile]:
    require_owner(actor_id, authority)
    return await users.list(query=query, limit=limit)


@router.get("/{user_id}", response_model=UserProfile)
async def get_user(
    user_id: str,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    users: Annotated[UserService, Depends(get_user_service)],
) -> UserProfile:
    require_owner(actor_id, authority)
    try:
        return await users.get(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
