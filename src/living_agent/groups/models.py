"""Bounded room contracts / 有界群聊合同。"""

from datetime import UTC, datetime
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Member(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    member_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=80)
    persona: str = Field(min_length=1, max_length=2000)


class RoomCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    members: list[Member] = Field(min_length=2, max_length=6)

    @model_validator(mode="after")
    def unique_members(self) -> Self:
        for values in (
            [member.member_id for member in self.members],
            [member.name for member in self.members],
        ):
            if len(values) != len(set(values)):
                raise ValueError("群成员 ID 和名字必须唯一 / Member IDs and names must be unique")
        return self


class GroupMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    speaker_id: str
    speaker_name: str
    role: Literal["owner", "agent"]
    content: str = Field(min_length=1, max_length=4000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Room(RoomCreate):
    room_id: str = Field(default_factory=lambda: str(uuid4()))
    messages: list[GroupMessage] = Field(default_factory=list, max_length=500)
    status: Literal["idle", "responding", "stopped", "interrupted", "failed"] = "idle"
    turn_id: str | None = None
    error_code: str | None = None
    version: int = 1
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SendMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=4000)
    mentions: list[str] = Field(default_factory=list, max_length=6)
