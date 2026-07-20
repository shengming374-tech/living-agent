"""Database-only registered user model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from living_agent.storage.database import Base


class RegisteredUserORM(Base):
    __tablename__ = "registered_users"
    __table_args__ = (Index("ix_registered_users_last_seen", "last_seen_at"),)

    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_conversation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
