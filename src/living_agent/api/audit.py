"""Owner-only audit read endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from living_agent.api.dependencies import get_audit, get_authority
from living_agent.audit.models import AuditEntry
from living_agent.audit.service import AuditService
from living_agent.models.events import AuthorityLevel
from living_agent.trust.authority import AuthorityResolver

router = APIRouter(prefix="/v1", tags=["audit"])


@router.get("/audit", response_model=list[AuditEntry])
async def list_audit(
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    audit: Annotated[AuditService, Depends(get_audit)],
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[AuditEntry]:
    if authority.resolve(actor_id, authenticated=True) is not AuthorityLevel.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="owner authority required",
        )
    return await audit.list_entries(limit=limit)
