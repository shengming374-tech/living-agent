"""Shared staged-test-deploy workflow for owner-managed files."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from living_agent.audit.service import AuditService
from living_agent.management.artifacts import (
    ArtifactConflictError,
    ArtifactKind,
    ArtifactNotFoundError,
    ArtifactRepository,
    ArtifactStage,
    ArtifactStateError,
    ArtifactVersion,
    ArtifactView,
    DeployResult,
    StageRequest,
    atomic_write,
    checksum,
)


class ManagedArtifactService(ABC):
    def __init__(
        self,
        *,
        kind: ArtifactKind,
        root: Path,
        allowed_paths: set[str],
        repository: ArtifactRepository,
        audit: AuditService,
        bootstrap_actor: str,
    ) -> None:
        self.kind = kind
        self.root = root.resolve()
        self.allowed_paths = frozenset(allowed_paths)
        self._repository = repository
        self._audit = audit
        self._bootstrap_actor = bootstrap_actor
        self._deployment_lock = asyncio.Lock()

    async def initialize(self) -> None:
        for artifact_path in sorted(self.allowed_paths):
            content = self._read_file(artifact_path)
            current = await self._repository.bootstrap(
                kind=self.kind,
                path=artifact_path,
                content=content,
                actor_id=self._bootstrap_actor,
            )
            if current.checksum != checksum(content):
                raise ArtifactConflictError(
                    f"{self.kind.value} file differs from its deployed version: {artifact_path}"
                )

    async def view(self, artifact_path: str) -> ArtifactView:
        self._require_path(artifact_path)
        current = await self._required_current(artifact_path)
        return self._view(current)

    async def history(self, artifact_path: str) -> list[ArtifactVersion]:
        self._require_path(artifact_path)
        return await self._repository.history(kind=self.kind, path=artifact_path)

    async def get_stage(self, stage_id: str) -> ArtifactStage:
        return await self._owned_stage(stage_id)

    async def stage(
        self,
        artifact_path: str,
        request: StageRequest,
        *,
        actor_id: str,
    ) -> ArtifactStage:
        self._require_path(artifact_path)
        validation = self.validate(artifact_path, request.content)
        stage = await self._repository.create_stage(
            kind=self.kind,
            path=artifact_path,
            content=request.content,
            expected_version=request.expected_version,
            actor_id=actor_id,
            validation=validation,
        )
        await self._audit.append(
            action=f"{self.kind.value}.staged",
            actor_id=actor_id,
            outcome="success",
            details={
                "stage_id": stage.stage_id,
                "artifact_path": artifact_path,
                "base_version": stage.base_version,
                "diff": stage.diff,
            },
        )
        return stage

    async def test(self, stage_id: str, *, actor_id: str) -> ArtifactStage:
        stage = await self._owned_stage(stage_id)
        results = await self.run_tests(stage)
        tested = await self._repository.mark_tested(stage_id, results)
        await self._audit.append(
            action=f"{self.kind.value}.tested",
            actor_id=actor_id,
            outcome="passed" if tested.tested else "failed",
            details={
                "stage_id": stage_id,
                "artifact_path": stage.artifact_path,
                "test_results": results,
            },
        )
        return tested

    async def deploy(
        self,
        stage_id: str,
        *,
        actor_id: str,
        change_type: str = "deploy",
    ) -> DeployResult:
        async with self._deployment_lock:
            stage = await self._owned_stage(stage_id)
            if stage.status.value != "staged" or not stage.tested:
                raise ArtifactStateError("stage must pass tests before deployment")
            current = await self._required_current(stage.artifact_path)
            if current.version != stage.base_version:
                raise ArtifactConflictError("artifact changed after staging")
            target = self._file_path(stage.artifact_path)
            old_content = target.read_text(encoding="utf-8")
            atomic_write(target, stage.content)
            try:
                deployed = await self._repository.deploy(
                    stage_id,
                    actor_id=actor_id,
                    change_type=change_type,
                )
            except Exception:
                atomic_write(target, old_content)
                raise
        result = DeployResult(
            artifact=self._view(deployed),
            recovery_version=current.version,
            restart_required=self.restart_required(stage.artifact_path),
        )
        await self._audit.append(
            action=f"{self.kind.value}.deployed",
            actor_id=actor_id,
            outcome="success",
            details={
                "stage_id": stage_id,
                "artifact_path": stage.artifact_path,
                "version": deployed.version,
                "recovery_version": current.version,
                "restart_required": result.restart_required,
            },
        )
        return result

    async def rollback(
        self,
        artifact_path: str,
        *,
        target_version: int,
        actor_id: str,
    ) -> DeployResult:
        self._require_path(artifact_path)
        current = await self._required_current(artifact_path)
        target = await self._repository.version(
            kind=self.kind,
            path=artifact_path,
            version=target_version,
        )
        if target.content == current.content:
            raise ArtifactStateError("rollback target equals the current content")
        stage = await self.stage(
            artifact_path,
            StageRequest(content=target.content, expected_version=current.version),
            actor_id=actor_id,
        )
        tested = await self.test(stage.stage_id, actor_id=actor_id)
        if not tested.tested:
            raise ArtifactStateError("rollback target failed current tests")
        result = await self.deploy(
            stage.stage_id,
            actor_id=actor_id,
            change_type="rollback",
        )
        await self._audit.append(
            action=f"{self.kind.value}.rolled_back",
            actor_id=actor_id,
            outcome="success",
            details={
                "artifact_path": artifact_path,
                "target_version": target_version,
                "deployed_version": result.artifact.version,
            },
        )
        return result

    @abstractmethod
    def validate(self, artifact_path: str, content: str) -> dict[str, Any]:
        """Validate a single candidate file and return structured results."""

    @abstractmethod
    async def run_tests(self, stage: ArtifactStage) -> dict[str, Any]:
        """Run cross-artifact or rendering checks for a staged candidate."""

    @abstractmethod
    def restart_required(self, artifact_path: str) -> bool:
        """Return whether the deployed artifact activates only after restart."""

    def _require_path(self, artifact_path: str) -> None:
        if artifact_path not in self.allowed_paths:
            raise ArtifactNotFoundError(f"unknown {self.kind.value} artifact")

    def _file_path(self, artifact_path: str) -> Path:
        self._require_path(artifact_path)
        path = (self.root / artifact_path).resolve()
        if self.root not in path.parents:
            raise ArtifactNotFoundError("artifact path escapes its root")
        return path

    def _read_file(self, artifact_path: str) -> str:
        path = self._file_path(artifact_path)
        if not path.is_file():
            raise ArtifactNotFoundError(f"managed file does not exist: {artifact_path}")
        return path.read_text(encoding="utf-8")

    async def _required_current(self, artifact_path: str) -> ArtifactVersion:
        current = await self._repository.current(kind=self.kind, path=artifact_path)
        if current is None:
            raise ArtifactNotFoundError("managed artifact not initialized")
        return current

    async def _owned_stage(self, stage_id: str) -> ArtifactStage:
        stage = await self._repository.get_stage(stage_id)
        if stage.artifact_kind is not self.kind or stage.artifact_path not in self.allowed_paths:
            raise ArtifactNotFoundError(f"stage does not belong to {self.kind.value}")
        return stage

    @staticmethod
    def _view(version: ArtifactVersion) -> ArtifactView:
        return ArtifactView(
            artifact_kind=version.artifact_kind,
            artifact_path=version.artifact_path,
            version=version.version,
            content=version.content,
            checksum=version.checksum,
        )
