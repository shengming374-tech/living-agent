"""Owner-only layered persona management endpoints."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from living_agent.api.dependencies import get_authority, get_persona_manager
from living_agent.api.management import ActorHeader, artifact_http_error, require_owner
from living_agent.management.artifacts import (
    ArtifactStage,
    ArtifactVersion,
    ArtifactView,
    DeployResult,
    StageRequest,
)
from living_agent.persona.manager import PersonaManager
from living_agent.trust.authority import AuthorityResolver

router = APIRouter(prefix="/v1/persona", tags=["persona"])


class PersonaLayer(StrEnum):
    IDENTITY = "identity"
    VALUES = "values"
    TRAITS = "traits"
    SPEECH = "speech"
    BOUNDARIES = "boundaries"
    GROWTH = "growth"


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_version: int = Field(ge=1)


def _path(layer: PersonaLayer) -> str:
    return f"{layer.value}.yaml"


@router.get("/{layer}", response_model=ArtifactView)
async def view_persona(
    layer: PersonaLayer,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    manager: Annotated[PersonaManager, Depends(get_persona_manager)],
) -> ArtifactView:
    require_owner(actor_id, authority)
    try:
        return await manager.view(_path(layer))
    except Exception as exc:
        raise artifact_http_error(exc) from exc


@router.get("/{layer}/history", response_model=list[ArtifactVersion])
async def persona_history(
    layer: PersonaLayer,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    manager: Annotated[PersonaManager, Depends(get_persona_manager)],
) -> list[ArtifactVersion]:
    require_owner(actor_id, authority)
    try:
        return await manager.history(_path(layer))
    except Exception as exc:
        raise artifact_http_error(exc) from exc


@router.post("/{layer}/stage", response_model=ArtifactStage)
async def stage_persona(
    layer: PersonaLayer,
    request: StageRequest,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    manager: Annotated[PersonaManager, Depends(get_persona_manager)],
) -> ArtifactStage:
    require_owner(actor_id, authority)
    try:
        return await manager.stage(_path(layer), request, actor_id=actor_id)
    except Exception as exc:
        raise artifact_http_error(exc) from exc


@router.post("/stages/{stage_id}/test", response_model=ArtifactStage)
async def test_persona(
    stage_id: str,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    manager: Annotated[PersonaManager, Depends(get_persona_manager)],
) -> ArtifactStage:
    require_owner(actor_id, authority)
    try:
        return await manager.test(stage_id, actor_id=actor_id)
    except Exception as exc:
        raise artifact_http_error(exc) from exc


@router.post("/stages/{stage_id}/deploy", response_model=DeployResult)
async def deploy_persona(
    stage_id: str,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    manager: Annotated[PersonaManager, Depends(get_persona_manager)],
) -> DeployResult:
    require_owner(actor_id, authority)
    try:
        return await manager.deploy(stage_id, actor_id=actor_id)
    except Exception as exc:
        raise artifact_http_error(exc) from exc


@router.post("/{layer}/rollback", response_model=DeployResult)
async def rollback_persona(
    layer: PersonaLayer,
    request: RollbackRequest,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    manager: Annotated[PersonaManager, Depends(get_persona_manager)],
) -> DeployResult:
    require_owner(actor_id, authority)
    try:
        return await manager.rollback(
            _path(layer),
            target_version=request.target_version,
            actor_id=actor_id,
        )
    except Exception as exc:
        raise artifact_http_error(exc) from exc
