"""Persistent user registration keyed only by authenticated stable identity."""

from __future__ import annotations

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from living_agent.models.events import SourceType, TrustedEvent
from living_agent.models.users import UserProfile
from living_agent.users.models import RegisteredUserORM


class UserNotFoundError(LookupError):
    pass


class UserRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def observe(
        self,
        event: TrustedEvent,
        *,
        display_name: str | None,
    ) -> tuple[UserProfile, bool, bool]:
        assert event.source_identity is not None
        updated = await self._update_existing(event, display_name=display_name)
        if updated is not None:
            return updated
        try:
            return await self._insert(event, display_name=display_name)
        except IntegrityError:
            updated = await self._update_existing(event, display_name=display_name)
            if updated is None:
                raise
            return updated

    async def _insert(
        self,
        event: TrustedEvent,
        *,
        display_name: str | None,
    ) -> tuple[UserProfile, bool, bool]:
        assert event.source_identity is not None
        async with self._sessions() as session, session.begin():
            record = RegisteredUserORM(
                user_id=event.source_identity,
                display_name=display_name,
                source_type=event.source_type.value,
                first_seen_at=event.created_at,
                last_seen_at=event.created_at,
                message_count=1,
                last_conversation_id=event.conversation_id,
            )
            session.add(record)
        return self._schema(record), True, False

    async def _update_existing(
        self,
        event: TrustedEvent,
        *,
        display_name: str | None,
    ) -> tuple[UserProfile, bool, bool] | None:
        assert event.source_identity is not None
        async with self._sessions() as session, session.begin():
            existing = await session.get(RegisteredUserORM, event.source_identity)
            if existing is None:
                return None
            name_changed = display_name is not None and display_name != existing.display_name
            values: dict[str, object] = {
                "source_type": event.source_type.value,
                "last_seen_at": event.created_at,
                "message_count": RegisteredUserORM.message_count + 1,
                "last_conversation_id": event.conversation_id,
            }
            if display_name is not None:
                values["display_name"] = display_name
            statement = (
                update(RegisteredUserORM)
                .where(RegisteredUserORM.user_id == event.source_identity)
                .values(**values)
                .returning(RegisteredUserORM)
            )
            record = (await session.scalars(statement)).one()
        return self._schema(record), False, name_changed

    async def list(self, *, query: str, limit: int) -> list[UserProfile]:
        statement = select(RegisteredUserORM)
        if query.strip():
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    RegisteredUserORM.user_id.ilike(pattern),
                    RegisteredUserORM.display_name.ilike(pattern),
                )
            )
        statement = statement.order_by(RegisteredUserORM.last_seen_at.desc()).limit(limit)
        async with self._sessions() as session:
            records = list((await session.scalars(statement)).all())
        return [self._schema(record) for record in records]

    async def get(self, user_id: str) -> UserProfile:
        async with self._sessions() as session:
            record = await session.get(RegisteredUserORM, user_id)
            if record is None:
                raise UserNotFoundError("registered user not found")
            return self._schema(record)

    @staticmethod
    def _schema(record: RegisteredUserORM) -> UserProfile:
        return UserProfile(
            user_id=record.user_id,
            display_name=record.display_name,
            source_type=SourceType(record.source_type),
            first_seen_at=record.first_seen_at,
            last_seen_at=record.last_seen_at,
            message_count=record.message_count,
            last_conversation_id=record.last_conversation_id,
        )
