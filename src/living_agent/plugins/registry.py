"""Discover and manage native plugin manifests without importing plugin code."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from living_agent.audit.service import AuditService
from living_agent.management.artifacts import atomic_write
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


class _PluginState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    enabled: dict[str, StrictBool]


class PluginRegistry:
    def __init__(self, root: Path, *, state_path: Path | None = None) -> None:
        self._root = root.resolve()
        self._state_path = state_path.resolve() if state_path is not None else None
        self._records: dict[str, PluginRecord] = {}
        self._enabled: set[str] = set()
        self._overrides: dict[str, bool] = {}
        self._state_lock = asyncio.Lock()

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

    async def initialize(
        self,
        *,
        default_enabled: list[str],
        actor_id: str,
        audit: AuditService,
    ) -> None:
        """Restore owner choices while treating configured plugins as defaults."""

        async with self._state_lock:
            for plugin_id in default_enabled:
                self.get(plugin_id)
            try:
                overrides = self._read_state()
            except (OSError, UnicodeError, ValidationError) as exc:
                # Corrupt owner choices never re-enable configured defaults.
                # 所有者状态损坏时禁用全部插件, 下一次显式开关会修复状态文件。
                overrides = dict.fromkeys(self._records, False)
                await audit.append(
                    action="plugin.state_invalid",
                    actor_id=actor_id,
                    outcome="disabled",
                    details={
                        "reason_code": "saved_plugin_state_unreadable",
                        "error_code": type(exc).__name__,
                    },
                )
            enabled = set(default_enabled)
            for plugin_id, chosen in overrides.items():
                if chosen:
                    enabled.add(plugin_id)
                else:
                    enabled.discard(plugin_id)
            self._enabled = enabled.intersection(self._records)
            self._overrides = overrides
            await audit.append(
                action="plugin.initialized",
                actor_id=actor_id,
                outcome="success",
                details={"enabled_plugins": sorted(self._enabled)},
            )

    async def enable(self, plugin_id: str, *, actor_id: str, audit: AuditService) -> None:
        await self._set_enabled(plugin_id, True, actor_id=actor_id, audit=audit)

    async def disable(self, plugin_id: str, *, actor_id: str, audit: AuditService) -> None:
        await self._set_enabled(plugin_id, False, actor_id=actor_id, audit=audit)

    async def _set_enabled(
        self,
        plugin_id: str,
        enabled: bool,
        *,
        actor_id: str,
        audit: AuditService,
    ) -> None:
        async with self._state_lock:
            self.get(plugin_id)
            overrides = {**self._overrides, plugin_id: enabled}
            if self._state_path is not None:
                atomic_write(
                    self._state_path,
                    _PluginState(enabled=overrides).model_dump_json(indent=2),
                )
            self._overrides = overrides
            if enabled:
                self._enabled.add(plugin_id)
            else:
                self._enabled.discard(plugin_id)
            await audit.append(
                action="plugin.enabled" if enabled else "plugin.disabled",
                actor_id=actor_id,
                outcome="success",
                details={"plugin_id": plugin_id},
            )

    def _read_state(self) -> dict[str, bool]:
        if self._state_path is None or not self._state_path.exists():
            return {}
        return _PluginState.model_validate_json(
            self._state_path.read_text(encoding="utf-8")
        ).enabled

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
