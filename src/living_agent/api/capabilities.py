"""Owner-only capability inventory and temporary-grant revocation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from living_agent.api.dependencies import get_audit, get_authority, get_broker
from living_agent.api.management import ActorHeader, require_owner
from living_agent.audit.service import AuditService
from living_agent.execution.broker import CapabilityBroker
from living_agent.models.capabilities import CapabilityGrant, CapabilitySnapshot
from living_agent.trust.authority import AuthorityResolver

router = APIRouter(prefix="/v1/capabilities", tags=["capabilities"])
GrantIdPath = Annotated[str, Path(min_length=36, max_length=36)]


@router.get("", response_model=CapabilitySnapshot)
async def capability_snapshot(
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    broker: Annotated[CapabilityBroker, Depends(get_broker)],
) -> CapabilitySnapshot:
    require_owner(actor_id, authority)
    return await broker.snapshot()


@router.delete("/grants/{grant_id}", response_model=CapabilityGrant)
async def revoke_capability_grant(
    grant_id: GrantIdPath,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    broker: Annotated[CapabilityBroker, Depends(get_broker)],
    audit: Annotated[AuditService, Depends(get_audit)],
) -> CapabilityGrant:
    require_owner(actor_id, authority)
    grant = await broker.revoke_grant_by_id(grant_id)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="active capability grant not found",
        )
    await audit.append(
        action="capability.grant_revoked",
        actor_id=actor_id,
        conversation_id=grant.conversation_id,
        outcome="success",
        details={
            "grant_id": grant.grant_id,
            "capability": grant.capability,
            "operations": sorted(grant.operations),
            "resource_scopes": sorted(grant.resource_scopes),
        },
    )
    return grant
