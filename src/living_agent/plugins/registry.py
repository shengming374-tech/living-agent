"""Discover and manage native plugin manifests without importing plugin code."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from living_agent.audit.service import AuditService
from living_agent.plugins.manifest import PluginManifest


@dataclass(frozen=True, slots=True)
class PluginRecord:
    manifest: PluginManifest
    root: Path


class PluginSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    version: str
    plugin_type: str
    risk_level: str
    enabled: bool
    operations: list[str]


class PluginRegistry:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._records: dict[str, PluginRecord] = {}
        self._enabled: set[str] = set()

    def discover(self) -> list[PluginRecord]:
        records: dict[str, PluginRecord] = {}
        if not self._root.exists():
            self._records = records
            return []
        for manifest_path in sorted(self._root.glob("*/manifest.yaml")):
            payload = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
            manifest = PluginManifest.model_validate(payload)
            if manifest.id in records:
                raise ValueError(f"duplicate plugin id: {manifest.id}")
            plugin_root = manifest_path.parent.resolve()
            self._validate_record(plugin_root, manifest)
            records[manifest.id] = PluginRecord(manifest=manifest, root=plugin_root)
        self._records = records
        self._enabled.intersection_update(records)
        return list(records.values())

    async def enable(self, plugin_id: str, *, actor_id: str, audit: AuditService) -> None:
        self.get(plugin_id)
        self._enabled.add(plugin_id)
        await audit.append(
            action="plugin.enabled",
            actor_id=actor_id,
            outcome="success",
            details={"plugin_id": plugin_id},
        )

    async def disable(self, plugin_id: str, *, actor_id: str, audit: AuditService) -> None:
        self.get(plugin_id)
        self._enabled.discard(plugin_id)
        await audit.append(
            action="plugin.disabled",
            actor_id=actor_id,
            outcome="success",
            details={"plugin_id": plugin_id},
        )

    def get(self, plugin_id: str) -> PluginRecord:
        try:
            return self._records[plugin_id]
        except KeyError as exc:
            raise KeyError(f"unknown plugin: {plugin_id}") from exc

    def get_enabled(self, plugin_id: str) -> PluginRecord:
        record = self.get(plugin_id)
        if plugin_id not in self._enabled:
            raise PluginDisabledError(f"plugin is disabled: {plugin_id}")
        return record

    def summaries(self) -> list[PluginSummary]:
        return [
            PluginSummary(
                id=record.manifest.id,
                name=record.manifest.name,
                version=record.manifest.version,
                plugin_type=record.manifest.plugin_type.value,
                risk_level=record.manifest.risk_level.value,
                enabled=record.manifest.id in self._enabled,
                operations=sorted(record.manifest.operations),
            )
            for record in sorted(self._records.values(), key=lambda item: item.manifest.id)
        ]

    @staticmethod
    def _validate_record(root: Path, manifest: PluginManifest) -> None:
        for operation_name, operation in manifest.operations.items():
            declaration = manifest.capabilities.get(operation.capability)
            if declaration is None:
                raise ValueError(
                    f"operation {operation_name} uses undeclared capability {operation.capability}"
                )
            if operation.broker_operation not in declaration.operations:
                raise ValueError(f"operation {operation_name} uses undeclared broker operation")
        module_path = root.joinpath(*manifest.entrypoint.split(".")).with_suffix(".py")
        package_path = root.joinpath(*manifest.entrypoint.split("."), "__init__.py")
        if not module_path.is_file() and not package_path.is_file():
            raise ValueError(f"plugin entrypoint does not exist: {manifest.entrypoint}")


class PluginDisabledError(RuntimeError):
    pass
