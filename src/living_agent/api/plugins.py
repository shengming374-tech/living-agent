"""Owner-controlled plugin inventory and runtime enable state."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from living_agent.api.dependencies import get_audit, get_authority, get_plugin_registry
from living_agent.audit.service import AuditService
from living_agent.models.events import AuthorityLevel
from living_agent.plugins.registry import PluginRegistry, PluginSummary
from living_agent.trust.authority import AuthorityResolver

router = APIRouter(prefix="/v1/plugins", tags=["plugins"])


def _require_owner(actor_id: str, authority: AuthorityResolver) -> None:
    if authority.resolve(actor_id, authenticated=True) is not AuthorityLevel.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="owner authority required",
        )


@router.get("", response_model=list[PluginSummary])
async def list_plugins(
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    registry: Annotated[PluginRegistry, Depends(get_plugin_registry)],
) -> list[PluginSummary]:
    _require_owner(actor_id, authority)
    return registry.summaries()


@router.post("/{plugin_id}/enable", response_model=PluginSummary)
async def enable_plugin(
    plugin_id: str,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    registry: Annotated[PluginRegistry, Depends(get_plugin_registry)],
    audit: Annotated[AuditService, Depends(get_audit)],
) -> PluginSummary:
    _require_owner(actor_id, authority)
    try:
        await registry.enable(plugin_id, actor_id=actor_id, audit=audit)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="plugin not found"
        ) from exc
    return next(summary for summary in registry.summaries() if summary.id == plugin_id)


@router.post("/{plugin_id}/disable", response_model=PluginSummary)
async def disable_plugin(
    plugin_id: str,
    actor_id: Annotated[str, Header(alias="X-Actor-ID")],
    authority: Annotated[AuthorityResolver, Depends(get_authority)],
    registry: Annotated[PluginRegistry, Depends(get_plugin_registry)],
    audit: Annotated[AuditService, Depends(get_audit)],
) -> PluginSummary:
    _require_owner(actor_id, authority)
    try:
        await registry.disable(plugin_id, actor_id=actor_id, audit=audit)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="plugin not found"
        ) from exc
    return next(summary for summary in registry.summaries() if summary.id == plugin_id)
