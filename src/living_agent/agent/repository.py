"""持久检查点与乐观并发控制。 / Persistent checkpoints with optimistic concurrency."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from living_agent.agent.contracts import AgentRun
from living_agent.storage.database import Base


class AgentRunORM(Base):
    __tablename__ = "agent_runs"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AgentNotFoundError(LookupError):
    pass


class AgentConflictError(ValueError):
    pass


class AgentRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def create(self, run: AgentRun) -> AgentRun:
        async with self._sessions() as session:
            session.add(
                AgentRunORM(
                    run_id=run.run_id,
                    status=run.status,
                    payload=run.model_dump(mode="json"),
                    version=run.version,
                    created_at=run.created_at,
                )
            )
            await session.commit()
        return run

    async def get(self, run_id: str) -> AgentRun:
        async with self._sessions() as session:
            row = await session.get(AgentRunORM, run_id)
            if row is None:
                raise AgentNotFoundError("agent run not found")
            return AgentRun.model_validate(row.payload)

    async def save(self, run: AgentRun) -> AgentRun:
        saved = run.model_copy(update={"version": run.version + 1, "updated_at": datetime.now(UTC)})
        async with self._sessions() as session:
            result = await session.execute(
                update(AgentRunORM)
                .where(
                    AgentRunORM.run_id == run.run_id,
                    AgentRunORM.version == run.version,
                )
                .values(
                    status=saved.status,
                    payload=saved.model_dump(mode="json"),
                    version=saved.version,
                )
            )
            if result.rowcount != 1:  # type: ignore[attr-defined]
                raise AgentConflictError("agent run changed; reload before continuing")
            await session.commit()
        return saved

    async def list_runs(self, limit: int = 100) -> list[AgentRun]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(AgentRunORM).order_by(AgentRunORM.created_at.desc()).limit(limit)
            )
            return [AgentRun.model_validate(row.payload) for row in rows]

    async def running(self) -> list[AgentRun]:
        async with self._sessions() as session:
            rows = await session.scalars(select(AgentRunORM).where(AgentRunORM.status == "running"))
            return [AgentRun.model_validate(row.payload) for row in rows]
