"""Strict host contracts for the supported NapCat OneBot 11 subset."""

from __future__ import annotations

import html
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from living_agent.models.events import (
    MAX_IMAGES_PER_EVENT,
    ImageInput,
    IngressEnvelope,
    SourceType,
)

NAPCAT_REPLY_CAPABILITY = "platform.napcat.message"
_CQ_PATTERN = re.compile(r"\[CQ:([a-zA-Z0-9_]+)(?:,([^\]]*))?\]")
_IDENTIFIER_PATTERN = re.compile(r"^[0-9]{1,32}$")
_MESSAGE_ID_PATTERN = re.compile(r"^-?[0-9]{1,32}$")


def _identifier(value: object, *, message_id: bool = False) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("OneBot identifiers must be integers or numeric strings")
    normalized = str(value)
    pattern = _MESSAGE_ID_PATTERN if message_id else _IDENTIFIER_PATTERN
    if pattern.fullmatch(normalized) is None:
        raise ValueError("invalid OneBot identifier")
    return normalized


class OneBotMessageSegment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_]+$")
    data: dict[str, Any] = Field(default_factory=dict)


class OneBotSender(BaseModel):
    model_config = ConfigDict(extra="allow")

    user_id: str | None = None
    nickname: str | None = Field(default=None, max_length=200)
    card: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=40)

    @field_validator("user_id", mode="before")
    @classmethod
    def normalize_user_id(cls, value: object) -> str | None:
        return None if value is None else _identifier(value)


class OneBotMessageEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    time: int
    self_id: str
    post_type: Literal["message"]
    message_type: Literal["private", "group"]
    sub_type: str = Field(default="normal", max_length=40)
    message_id: str
    user_id: str
    group_id: str | None = None
    message: str | list[OneBotMessageSegment]
    raw_message: str = Field(default="", max_length=100000)
    sender: OneBotSender = Field(default_factory=OneBotSender)

    @field_validator("self_id", "user_id", "group_id", mode="before")
    @classmethod
    def normalize_identifier(cls, value: object) -> str | None:
        return None if value is None else _identifier(value)

    @field_validator("message_id", mode="before")
    @classmethod
    def normalize_message_id(cls, value: object) -> str:
        return _identifier(value, message_id=True)

    @model_validator(mode="after")
    def require_group_id(self) -> OneBotMessageEvent:
        if self.message_type == "group" and self.group_id is None:
            raise ValueError("group_id is required for group messages")
        if isinstance(self.message, list) and len(self.message) > 200:
            raise ValueError("OneBot message has too many segments")
        return self


class OneBotMetaEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    time: int
    self_id: str
    post_type: Literal["meta_event"]
    meta_event_type: Literal["lifecycle", "heartbeat"]

    @field_validator("self_id", mode="before")
    @classmethod
    def normalize_self_id(cls, value: object) -> str:
        return _identifier(value)


class OneBotActionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: Literal["ok", "failed"]
    retcode: int
    data: dict[str, Any] | None = None
    echo: str


class NapCatReplyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self_id: str
    message_type: Literal["private", "group"]
    target_id: str
    message: str = Field(min_length=1, max_length=4000)
    source_message_id: str

    @field_validator("self_id", "target_id", mode="before")
    @classmethod
    def normalize_identifier(cls, value: object) -> str:
        return _identifier(value)

    @field_validator("source_message_id", mode="before")
    @classmethod
    def normalize_source_message_id(cls, value: object) -> str:
        return _identifier(value, message_id=True)


class NormalizedNapCatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    envelope: IngressEnvelope
    reply: NapCatReplyArguments


def normalize_message(event: OneBotMessageEvent) -> NormalizedNapCatMessage:
    text, mentions_agent, mentions_other, segment_types, images = _message_text(
        event.message,
        event.self_id,
    )
    if not text and event.raw_message:
        text, raw_mentions, raw_mentions_other, raw_types, raw_images = _string_message(
            event.raw_message,
            event.self_id,
        )
        mentions_agent = mentions_agent or raw_mentions
        mentions_other = mentions_other or raw_mentions_other
        segment_types = raw_types
        if not images:
            images = raw_images
    target_id = event.user_id if event.message_type == "private" else event.group_id
    if target_id is None:
        raise ValueError("message target is missing")
    conversation_id = (
        f"napcat:{event.self_id}:private:{event.user_id}"
        if event.message_type == "private"
        else f"napcat:{event.self_id}:group:{target_id}"
    )
    content = {
        "text": text,
        "mentions_agent": mentions_agent,
        "mentions_other": mentions_other,
        "platform": "napcat.onebot11",
        "platform_message_id": event.message_id,
        "segment_types": segment_types,
    }
    if images:
        content["images"] = images
    return NormalizedNapCatMessage(
        envelope=IngressEnvelope(
            event_type="napcat.onebot11.message",
            content=content,
            source_type=(
                SourceType.DIRECT_MESSAGE
                if event.message_type == "private"
                else SourceType.GROUP_MESSAGE
            ),
            source_identity=f"napcat:{event.self_id}:qq:{event.user_id}",
            display_name=event.sender.card or event.sender.nickname,
            conversation_id=conversation_id,
            authenticated=True,
        ),
        reply=NapCatReplyArguments(
            self_id=event.self_id,
            message_type=event.message_type,
            target_id=target_id,
            message="pending",
            source_message_id=event.message_id,
        ),
    )


def onebot_reply_action(arguments: NapCatReplyArguments) -> tuple[str, dict[str, Any]]:
    target_key = "user_id" if arguments.message_type == "private" else "group_id"
    action = "send_private_msg" if arguments.message_type == "private" else "send_group_msg"
    return action, {
        target_key: arguments.target_id,
        "message": [{"type": "text", "data": {"text": arguments.message}}],
    }


def napcat_reply_scope_matches(arguments: BaseModel, resource_scope: str) -> bool:
    if not isinstance(arguments, NapCatReplyArguments):
        return False
    conversation = (
        f"napcat:{arguments.self_id}:private:{arguments.target_id}"
        if arguments.message_type == "private"
        else f"napcat:{arguments.self_id}:group:{arguments.target_id}"
    )
    return resource_scope.startswith(f"{conversation}/event:")


def _message_text(
    message: str | list[OneBotMessageSegment],
    self_id: str,
) -> tuple[str, bool, bool, list[str], list[dict[str, str]]]:
    if isinstance(message, str):
        return _string_message(message, self_id)
    parts: list[str] = []
    mentions_agent = False
    mentions_other = False
    segment_types: list[str] = []
    images: list[dict[str, str]] = []
    for segment in message:
        segment_types.append(segment.type)
        if segment.type == "text":
            value = segment.data.get("text")
            if isinstance(value, str):
                parts.append(value)
        elif segment.type == "at":
            target = _mention_target(segment.data.get("qq"))
            mentions_agent = mentions_agent or target == self_id
            mentions_other = mentions_other or (target is not None and target != self_id)
            if target != self_id:
                parts.append("[@user]")
        elif segment.type == "image":
            image = _image_reference(segment.data)
            if image is not None:
                _append_image(images, image)
            else:
                parts.append("[image]")
        elif segment.type != "reply":
            parts.append(f"[{segment.type}]")
    return (
        " ".join("".join(parts).split()),
        mentions_agent,
        mentions_other,
        segment_types,
        images,
    )


def _string_message(
    message: str,
    self_id: str,
) -> tuple[str, bool, bool, list[str], list[dict[str, str]]]:
    mentions_agent = False
    mentions_other = False
    segment_types: list[str] = []
    images: list[dict[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        nonlocal mentions_agent, mentions_other
        kind = match.group(1)
        parameters = match.group(2) or ""
        segment_types.append(kind)
        if kind == "at":
            values = dict(item.split("=", 1) for item in parameters.split(",") if "=" in item)
            target = _mention_target(values.get("qq"))
            mentions_agent = mentions_agent or target == self_id
            mentions_other = mentions_other or (target is not None and target != self_id)
            return "" if target == self_id else "[@user]"
        if kind == "reply":
            return ""
        if kind == "image":
            values = dict(item.split("=", 1) for item in parameters.split(",") if "=" in item)
            image = _image_reference(values)
            if image is not None:
                _append_image(images, image)
                return ""
        return f"[{kind}]"

    text = html.unescape(_CQ_PATTERN.sub(replace, message))
    return " ".join(text.split()), mentions_agent, mentions_other, segment_types, images


def _mention_target(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    normalized = str(value)
    return normalized if _IDENTIFIER_PATTERN.fullmatch(normalized) is not None else None


def _image_reference(data: dict[str, Any]) -> dict[str, str] | None:
    candidates = [data.get("url"), data.get("file")]
    for candidate in candidates:
        if not isinstance(candidate, str) or not candidate:
            continue
        normalized = html.unescape(candidate)
        if normalized.startswith("base64://"):
            normalized = f"data:image/jpeg;base64,{normalized.removeprefix('base64://')}"
        try:
            image = ImageInput(url=normalized)
        except ValueError:
            continue
        return image.model_dump()
    return None


def _append_image(images: list[dict[str, str]], image: dict[str, str]) -> None:
    if len(images) >= MAX_IMAGES_PER_EVENT:
        return
    if any(existing["url"] == image["url"] for existing in images):
        return
    images.append(image)
