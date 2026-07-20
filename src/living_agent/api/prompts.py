"""Owner-only Prompt Lab with root-policy second authentication."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from living_agent.api.dependencies import (
    get_authority,
    get_prompt_manager,
    get_runtime,
    get_settings,
)
from living_agent.api.management import (
    ActorHeader,
    SecondFactorHeader,
    artifact_http_error,
    require_owner,
    require_second_factor,
)
from living_agent.cognition.context_compiler import CompiledContext
from living_agent.config import Settings
from living_agent.management.artifacts import (
    ArtifactStage,
    ArtifactVersion,
    DeployResult,
    StageRequest,
)
from living_agent.models.events import IngressEnvelope
from living_agent.prompts.manager import PromptManager, PromptRenderRequest, PromptRenderResult
from living_agent.runtime.runtime import AgentRuntime
from living_agent.trust.authority import AuthorityResolver

router = APIRouter(prefix="/v1/prompts", tags=["prompts"])


class PromptView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_path: str
    version: int
    content: str
    checksum: str
    token_estimate: int
    variables: list[str]


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_version: int = Field(ge=1)


class ContextPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope: IngressEnvelope
    current_task: dict[str, Any] | None = None
    available_capabilities: list[str] = Field(default_factory=list)


def _path(category: str, name: str) -> str:
    return f"{category}/{name}.txt"


def _root_auth(
    artifact_path: str,
    second_factor: str | None,
    settings: Settings,
) -> None:
    if PromptManager.is_root_path(artifact_path):
        require_second_factor(second_factor, settings)


@router.post("/context-preview", response_model=CompiledContext)
async def context_preview(
    request: ContextPreviewRequest,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    runtime: Annotated[AgentRuntime, Depends(get_runtime)],
) -> CompiledContext:
    require_owner(actor_id, authority)
    return runtime.compile_context_preview(
        request.envelope,
        current_task=request.current_task,
        available_capabilities=request.available_capabilities,
    )


@router.get("/{category}/{name}", response_model=PromptView)
async def view_prompt(
    category: str,
    name: str,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    manager: Annotated[PromptManager, Depends(get_prompt_manager)],
) -> PromptView:
    require_owner(actor_id, authority)
    artifact_path = _path(category, name)
    try:
        view = await manager.view(artifact_path)
        validation = manager.validate(artifact_path, view.content)
        return PromptView(
            artifact_path=artifact_path,
            version=view.version,
            content=view.content,
            checksum=view.checksum,
            token_estimate=validation["token_estimate"],
            variables=validation["variables"],
        )
    except Exception as exc:
        raise artifact_http_error(exc) from exc


@router.get("/{category}/{name}/history", response_model=list[ArtifactVersion])
async def prompt_history(
    category: str,
    name: str,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    manager: Annotated[PromptManager, Depends(get_prompt_manager)],
) -> list[ArtifactVersion]:
    require_owner(actor_id, authority)
    try:
        return await manager.history(_path(category, name))
    except Exception as exc:
        raise artifact_http_error(exc) from exc


@router.post("/{category}/{name}/stage", response_model=ArtifactStage)
async def stage_prompt(
    category: str,
    name: str,
    request: StageRequest,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    settings: Annotated[Settings, Depends(get_settings)],
    manager: Annotated[PromptManager, Depends(get_prompt_manager)],
    second_factor: SecondFactorHeader = None,
) -> ArtifactStage:
    require_owner(actor_id, authority)
    artifact_path = _path(category, name)
    _root_auth(artifact_path, second_factor, settings)
    try:
        return await manager.stage(artifact_path, request, actor_id=actor_id)
    except Exception as exc:
        raise artifact_http_error(exc) from exc


@router.post("/stages/{stage_id}/test", response_model=ArtifactStage)
async def test_prompt(
    stage_id: str,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    manager: Annotated[PromptManager, Depends(get_prompt_manager)],
) -> ArtifactStage:
    require_owner(actor_id, authority)
    try:
        return await manager.test(stage_id, actor_id=actor_id)
    except Exception as exc:
        raise artifact_http_error(exc) from exc


@router.post("/stages/{stage_id}/deploy", response_model=DeployResult)
async def deploy_prompt(
    stage_id: str,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    settings: Annotated[Settings, Depends(get_settings)],
    manager: Annotated[PromptManager, Depends(get_prompt_manager)],
    second_factor: SecondFactorHeader = None,
) -> DeployResult:
    require_owner(actor_id, authority)
    try:
        stage = await manager.get_stage(stage_id)
        _root_auth(stage.artifact_path, second_factor, settings)
        return await manager.deploy(stage_id, actor_id=actor_id)
    except Exception as exc:
        raise artifact_http_error(exc) from exc


@router.post("/{category}/{name}/rollback", response_model=DeployResult)
async def rollback_prompt(
    category: str,
    name: str,
    request: RollbackRequest,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    settings: Annotated[Settings, Depends(get_settings)],
    manager: Annotated[PromptManager, Depends(get_prompt_manager)],
    second_factor: SecondFactorHeader = None,
) -> DeployResult:
    require_owner(actor_id, authority)
    artifact_path = _path(category, name)
    _root_auth(artifact_path, second_factor, settings)
    try:
        return await manager.rollback(
            artifact_path,
            target_version=request.target_version,
            actor_id=actor_id,
        )
    except Exception as exc:
        raise artifact_http_error(exc) from exc


@router.post("/{category}/{name}/render", response_model=PromptRenderResult)
async def render_prompt(
    category: str,
    name: str,
    request: PromptRenderRequest,
    actor_id: ActorHeader,
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    manager: Annotated[PromptManager, Depends(get_prompt_manager)],
) -> PromptRenderResult:
    require_owner(actor_id, authority)
    try:
        return await manager.render(_path(category, name), request)
    except Exception as exc:
        raise artifact_http_error(exc) from exc
