"""Schemas, repository, and atomic file helpers for managed artifacts."""

from __future__ import annotations

import difflib
import hashlib
import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from living_agent.management.models import ArtifactStageORM, ArtifactVersionORM


class ArtifactKind(StrEnum):
    PERSONA = "persona"
    PROMPT = "prompt"


class ArtifactStatus(StrEnum):
    STAGED = "staged"
    DEPLOYED = "deployed"
    REJECTED = "rejected"


class ArtifactVersion(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    artifact_kind: ArtifactKind
    artifact_path: str
    version: int
    content: str
    checksum: str
    change_type: str
    actor_id: str
    created_at: datetime


class ArtifactStage(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    stage_id: str
    artifact_kind: ArtifactKind
    artifact_path: str
    base_version: int
    content: str
    diff: str
    validation: dict[str, Any]
    test_results: dict[str, Any]
    tested: bool
    status: ArtifactStatus
    actor_id: str
    created_at: datetime
    updated_at: datetime


class ArtifactView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_kind: ArtifactKind
    artifact_path: str
    version: int
    content: str
    checksum: str


class StageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=200_000)
    expected_version: int = Field(ge=1)


class DeployResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact: ArtifactView
    recovery_version: int
    restart_required: bool


class ArtifactNotFoundError(LookupError):
    pass


class ArtifactConflictError(RuntimeError):
    pass


class ArtifactStateError(RuntimeError):
    pass


def checksum(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def unified_diff(path: str, before: str, after: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"{path}@current",
            tofile=f"{path}@staged",
        )
    )


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ArtifactRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def bootstrap(
        self,
        *,
        kind: ArtifactKind,
        path: str,
        content: str,
        actor_id: str,
    ) -> ArtifactVersion:
        current = await self.current(kind=kind, path=path, required=False)
        if current is not None:
            return current
        record = ArtifactVersionORM(
            row_id=str(uuid4()),
            artifact_kind=kind.value,
            artifact_path=path,
            version=1,
            content=content,
            checksum=checksum(content),
            change_type="bootstrap",
            actor_id=actor_id,
            created_at=datetime.now(UTC),
        )
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
        return ArtifactVersion.model_validate(record)

    async def current(
        self,
        *,
        kind: ArtifactKind,
        path: str,
        required: bool = True,
    ) -> ArtifactVersion | None:
        statement = (
            select(ArtifactVersionORM)
            .where(
                ArtifactVersionORM.artifact_kind == kind.value,
                ArtifactVersionORM.artifact_path == path,
            )
            .order_by(ArtifactVersionORM.version.desc())
            .limit(1)
        )
        async with self._sessions() as session:
            record = await session.scalar(statement)
        if record is None:
            if required:
                raise ArtifactNotFoundError("managed artifact not found")
            return None
        return ArtifactVersion.model_validate(record)

    async def version(self, *, kind: ArtifactKind, path: str, version: int) -> ArtifactVersion:
        statement = select(ArtifactVersionORM).where(
            ArtifactVersionORM.artifact_kind == kind.value,
            ArtifactVersionORM.artifact_path == path,
            ArtifactVersionORM.version == version,
        )
        async with self._sessions() as session:
            record = await session.scalar(statement)
        if record is None:
            raise ArtifactNotFoundError("artifact version not found")
        return ArtifactVersion.model_validate(record)

    async def history(self, *, kind: ArtifactKind, path: str) -> list[ArtifactVersion]:
        statement = (
            select(ArtifactVersionORM)
            .where(
                ArtifactVersionORM.artifact_kind == kind.value,
                ArtifactVersionORM.artifact_path == path,
            )
            .order_by(ArtifactVersionORM.version)
        )
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        if not records:
            raise ArtifactNotFoundError("artifact history not found")
        return [ArtifactVersion.model_validate(record) for record in records]

    async def create_stage(
        self,
        *,
        kind: ArtifactKind,
        path: str,
        content: str,
        expected_version: int,
        actor_id: str,
        validation: dict[str, Any],
    ) -> ArtifactStage:
        current = await self.current(kind=kind, path=path)
        if current is None or current.version != expected_version:
            raise ArtifactConflictError("artifact version does not match")
        if current.content == content:
            raise ArtifactStateError("staged content is unchanged")
        now = datetime.now(UTC)
        record = ArtifactStageORM(
            stage_id=str(uuid4()),
            artifact_kind=kind.value,
            artifact_path=path,
            base_version=expected_version,
            content=content,
            diff=unified_diff(path, current.content, content),
            validation=validation,
            test_results={},
            tested=False,
            status=ArtifactStatus.STAGED.value,
            actor_id=actor_id,
            created_at=now,
            updated_at=now,
        )
        async with self._sessions() as session:
            session.add(record)
            await session.commit()
        return ArtifactStage.model_validate(record)

    async def get_stage(self, stage_id: str) -> ArtifactStage:
        async with self._sessions() as session:
            record = await session.get(ArtifactStageORM, stage_id)
        if record is None:
            raise ArtifactNotFoundError("artifact stage not found")
        return ArtifactStage.model_validate(record)

    async def mark_tested(self, stage_id: str, results: dict[str, Any]) -> ArtifactStage:
        async with self._sessions() as session, session.begin():
            record = await session.get(ArtifactStageORM, stage_id)
            if record is None:
                raise ArtifactNotFoundError("artifact stage not found")
            if record.status != ArtifactStatus.STAGED.value:
                raise ArtifactStateError("only staged artifacts can be tested")
            record.tested = bool(results.get("passed", False))
            record.test_results = results
            record.updated_at = datetime.now(UTC)
        return ArtifactStage.model_validate(record)

    async def deploy(
        self,
        stage_id: str,
        *,
        actor_id: str,
        change_type: str = "deploy",
    ) -> ArtifactVersion:
        async with self._sessions() as session, session.begin():
            stage = await session.get(ArtifactStageORM, stage_id)
            if stage is None:
                raise ArtifactNotFoundError("artifact stage not found")
            if stage.status != ArtifactStatus.STAGED.value or not stage.tested:
                raise ArtifactStateError("stage must pass tests before deployment")
            current_version = await session.scalar(
                select(func.max(ArtifactVersionORM.version)).where(
                    ArtifactVersionORM.artifact_kind == stage.artifact_kind,
                    ArtifactVersionORM.artifact_path == stage.artifact_path,
                )
            )
            if current_version != stage.base_version:
                raise ArtifactConflictError("artifact changed after staging")
            record = ArtifactVersionORM(
                row_id=str(uuid4()),
                artifact_kind=stage.artifact_kind,
                artifact_path=stage.artifact_path,
                version=stage.base_version + 1,
                content=stage.content,
                checksum=checksum(stage.content),
                change_type=change_type,
                actor_id=actor_id,
                created_at=datetime.now(UTC),
            )
            session.add(record)
            stage.status = ArtifactStatus.DEPLOYED.value
            stage.updated_at = datetime.now(UTC)
        return ArtifactVersion.model_validate(record)
