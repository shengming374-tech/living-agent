"""Shared authorization and errors for owner-managed artifacts."""

from __future__ import annotations

import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from living_agent.config import Settings
from living_agent.management.artifacts import (
    ArtifactConflictError,
    ArtifactNotFoundError,
    ArtifactStateError,
)
from living_agent.models.events import AuthorityLevel
from living_agent.trust.authority import AuthorityResolver

ActorHeader = Annotated[str, Header(alias="X-Actor-ID")]
SecondFactorHeader = Annotated[str | None, Header(alias="X-Second-Factor")]
router = APIRouter(prefix="/v1/management", tags=["management"])


class ManagementSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_id: str
    authority_level: AuthorityLevel
    management_auth_required: bool


@router.get("/session")
async def management_session(
    request: Request,
    actor_id: ActorHeader,
) -> ManagementSessionResponse:
    authority: AuthorityResolver = request.app.state.authority
    return ManagementSessionResponse(
        actor_id=actor_id,
        authority_level=authority.resolve(actor_id, authenticated=True),
        management_auth_required=request.app.state.management_authenticator.required,
    )


def require_owner(actor_id: str, authority: AuthorityResolver) -> None:
    if authority.resolve(actor_id, authenticated=True) is not AuthorityLevel.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="owner authority required"
        )


def require_second_factor(value: str | None, settings: Settings) -> None:
    configured = settings.root_prompt_second_factor_sha256
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="root prompt changes are disabled until second-factor hash is configured",
        )
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="second factor required",
        )
    supplied = hashlib.sha256(value.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(supplied, configured.lower()):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid second factor")


def artifact_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, ArtifactNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ArtifactConflictError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (ArtifactStateError, ValueError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="artifact operation failed"
    )
