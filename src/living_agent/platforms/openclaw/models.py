"""Contracts for the authenticated OpenClaw channel bridge."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from living_agent.models.conversation import TurnDecision
from living_agent.models.events import IngressEnvelope, SourceType

OPENCLAW_REPLY_CAPABILITY = "platform.openclaw.message"
ShortReply = Annotated[str, Field(min_length=1, max_length=4000)]


def _stable_identifier(value: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 255:
        raise ValueError("OpenClaw identifiers must contain 1 to 255 characters")
    if any(ord(character) < 0x20 or character.isspace() for character in normalized):
        raise ValueError("OpenClaw identifiers cannot contain whitespace or control characters")
    return normalized


class OpenClawBridgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1]
    channel_id: str
    account_id: str
    conversation_id: str
    sender_id: str
    sender_name: str | None = Field(default=None, max_length=200)
    message_id: str
    content: str = Field(min_length=1, max_length=100000)
    timestamp_ms: int = Field(ge=0)
    is_group: bool = False
    session_key: str | None = Field(default=None, max_length=500)
    run_id: str | None = Field(default=None, max_length=100)

    @field_validator(
        "channel_id",
        "account_id",
        "conversation_id",
        "sender_id",
        "message_id",
    )
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return _stable_identifier(value)


class OpenClawReplyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: str
    account_id: str
    conversation_id: str
    message: str = Field(min_length=1, max_length=4000)
    messages: list[ShortReply] = Field(default_factory=list, max_length=3)
    source_message_id: str

    @field_validator("channel_id", "account_id", "conversation_id", "source_message_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return _stable_identifier(value)


class OpenClawBridgeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = 1
    handled: Literal[True] = True
    event_id: str | None
    turn: TurnDecision | None
    message: str | None
    messages: list[ShortReply] = Field(default_factory=list, max_length=3)
    reason_code: str


class NormalizedOpenClawMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope: IngressEnvelope
    reply: OpenClawReplyArguments


def normalize_openclaw_message(request: OpenClawBridgeRequest) -> NormalizedOpenClawMessage:
    chat_kind = "group" if request.is_group else "direct"
    namespace = f"openclaw:{request.channel_id}:{request.account_id}"
    return NormalizedOpenClawMessage(
        envelope=IngressEnvelope(
            event_type="openclaw.channel.message",
            content={
                "text": request.content,
                "mentions_agent": not request.is_group,
                "platform": request.channel_id,
                "platform_message_id": request.message_id,
            },
            source_type=(
                SourceType.GROUP_MESSAGE if request.is_group else SourceType.DIRECT_MESSAGE
            ),
            source_identity=f"{namespace}:user:{request.sender_id}",
            display_name=request.sender_name,
            conversation_id=f"{namespace}:{chat_kind}:{request.conversation_id}",
            authenticated=True,
        ),
        reply=OpenClawReplyArguments(
            channel_id=request.channel_id,
            account_id=request.account_id,
            conversation_id=request.conversation_id,
            message="pending",
            source_message_id=request.message_id,
        ),
    )


def openclaw_reply_scope_matches(arguments: BaseModel, resource_scope: str) -> bool:
    if not isinstance(arguments, OpenClawReplyArguments):
        return False
    conversation = (
        f"openclaw:{arguments.channel_id}:{arguments.account_id}"
        f":direct:{arguments.conversation_id}"
    )
    return resource_scope.startswith(f"{conversation}/event:")
