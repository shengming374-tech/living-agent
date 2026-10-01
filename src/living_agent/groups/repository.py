"""Persistent rooms with revision checks / 带版本检查的持久群聊。"""

from typing import Any

from sqlalchemy import JSON, Integer, String, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from living_agent.groups.models import Room
from living_agent.storage.database import Base


class RoomORM(Base):
    __tablename__ = "group_rooms"
    room_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class RoomConflictError(ValueError):
    pass


class RoomRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list_rooms(self) -> list[Room]:
        async with self._sessions() as session:
            rows = await session.scalars(select(RoomORM))
            return sorted(
                (Room.model_validate(row.payload) for row in rows),
                key=lambda room: room.created_at,
                reverse=True,
            )

    async def get(self, room_id: str) -> Room:
        async with self._sessions() as session:
            row = await session.get(RoomORM, room_id)
            if row is None:
                raise LookupError("群聊不存在 / Room not found")
            return Room.model_validate(row.payload)

    async def create(self, room: Room) -> Room:
        async with self._sessions() as session:
            session.add(
                RoomORM(
                    room_id=room.room_id, payload=room.model_dump(mode="json"), version=room.version
                )
            )
            await session.commit()
        return room

    async def save(self, room: Room) -> Room:
        updated = room.model_copy(update={"version": room.version + 1})
        async with self._sessions() as session:
            result = await session.execute(
                update(RoomORM)
                .where(RoomORM.room_id == room.room_id, RoomORM.version == room.version)
                .values(payload=updated.model_dump(mode="json"), version=updated.version)
            )
            if result.rowcount != 1:  # type: ignore[attr-defined]
                raise RoomConflictError("群聊已更新, 请重读 / Room changed; reload")
            await session.commit()
        return updated
