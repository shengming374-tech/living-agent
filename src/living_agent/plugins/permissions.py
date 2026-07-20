"""Manifest-level least-privilege checks before the global broker."""

from living_agent.models.capabilities import CapabilityRequest
from living_agent.plugins.manifest import PluginManifest


class PluginPermissionError(PermissionError):
    pass


def require_declared_permission(
    manifest: PluginManifest,
    request: CapabilityRequest,
) -> None:
    declaration = manifest.capabilities.get(request.capability)
    if declaration is None:
        raise PluginPermissionError("plugin capability is not declared")
    if request.operation not in declaration.operations:
        raise PluginPermissionError("plugin operation is not declared")
    if not _scope_matches(request.resource_scope, declaration.scopes):
        raise PluginPermissionError("plugin resource scope is not declared")


def _scope_matches(requested: str, declared: set[str]) -> bool:
    return any(
        scope == "*"
        or scope == requested
        or (scope.endswith("/*") and requested.startswith(scope[:-1]))
        for scope in declared
    )
