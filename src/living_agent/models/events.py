"""Trusted ingress event schemas."""

from __future__ import annotations

import base64
import binascii
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from ipaddress import ip_address
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_IMAGES_PER_EVENT = 4
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TEXT_CONTENT_CHARS = 12_000
MAX_CONTENT_JSON_BYTES = 32 * 1024 * 1024
_MAX_DATA_URL_CHARS = (MAX_IMAGE_BYTES * 4 // 3) + 128
_SUPPORTED_IMAGE_MEDIA_TYPES = frozenset({"image/gif", "image/jpeg", "image/png", "image/webp"})
_BLOCKED_IMAGE_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".intranet",
    ".home.arpa",
)
_DATA_IMAGE_PATTERN = re.compile(
    r"^data:(image/(?:gif|jpeg|png|webp));base64,([A-Za-z0-9+/]+={0,2})$"
)


class SourceType(StrEnum):
    DIRECT_MESSAGE = "direct_message"
    GROUP_MESSAGE = "group_message"
    WEBPAGE = "webpage"
    FILE = "file"
    TOOL_RESULT = "tool_result"
    PLUGIN_RESULT = "plugin_result"
    TIMER = "timer"
    AGENT_MESSAGE = "agent_message"


class TrustLevel(StrEnum):
    TRUSTED = "trusted"
    AUTHENTICATED = "authenticated"
    UNTRUSTED = "untrusted"


class AuthorityLevel(StrEnum):
    SYSTEM = "system"
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    ANONYMOUS = "anonymous"


class ImageInput(BaseModel):
    """A bounded image reference passed through to a vision-capable model."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=_MAX_DATA_URL_CHARS, repr=False)
    detail: Literal["auto", "low", "high"] = "auto"

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.startswith("data:"):
            _data_image_size(normalized)
            return normalized
        if len(normalized) > 4096:
            raise ValueError("remote image URL is too long")
        if any(ord(character) < 0x20 or character.isspace() for character in normalized):
            raise ValueError("image URL cannot contain whitespace or control characters")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("image URL must use HTTP(S) or a supported Base64 data URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise ValueError("image URL cannot contain credentials or a fragment")
        if not is_safe_image_url(normalized):
            raise ValueError("image URL cannot target a private or local network address")
        return normalized

    @property
    def data_bytes(self) -> int:
        if not self.url.startswith("data:"):
            return 0
        match = _DATA_IMAGE_PATTERN.fullmatch(self.url)
        if match is None:
            return 0
        encoded = match.group(2)
        padding = len(encoded) - len(encoded.rstrip("="))
        return len(encoded) * 3 // 4 - padding

    @property
    def media_type(self) -> str | None:
        if not self.url.startswith("data:"):
            return None
        match = _DATA_IMAGE_PATTERN.fullmatch(self.url)
        return match.group(1) if match is not None else None


def image_inputs(content: str | dict[str, Any]) -> list[ImageInput]:
    """Return validated image inputs without trusting arbitrary stored dictionaries."""

    if not isinstance(content, dict):
        return []
    raw_images = content.get("images")
    if not isinstance(raw_images, list):
        return []
    images: list[ImageInput] = []
    for item in raw_images[:MAX_IMAGES_PER_EVENT]:
        try:
            images.append(ImageInput.model_validate(item))
        except (TypeError, ValueError):
            continue
    return images


def image_descriptors(content: str | dict[str, Any]) -> list[dict[str, str | int]]:
    """Describe image inputs without exposing URLs or inline image bytes."""

    descriptors: list[dict[str, str | int]] = []
    for image in image_inputs(content):
        descriptor: dict[str, str | int] = {
            "detail": image.detail,
            "source": "data_url" if image.url.startswith("data:") else "remote_url",
        }
        if image.media_type is not None:
            descriptor["media_type"] = image.media_type
            descriptor["bytes"] = image.data_bytes
        descriptors.append(descriptor)
    return descriptors


def is_safe_image_url(value: str) -> bool:
    """Reject URL forms that can target local, private, or link-local services."""

    parsed = urlsplit(value)
    if parsed.scheme == "data":
        return True
    hostname = (parsed.hostname or "").rstrip(".").casefold()
    if not hostname:
        return False
    if hostname == "localhost" or hostname.endswith(_BLOCKED_IMAGE_HOST_SUFFIXES):
        return False
    try:
        return ip_address(hostname).is_global
    except ValueError:
        # Hostnames are allowed so public HTTPS providers can be used without
        # making synchronous DNS lookups part of request validation.
        return True


def _validate_content_images(value: str | dict[str, Any]) -> str | dict[str, Any]:
    _validate_content_size(value)
    if not isinstance(value, dict) or "images" not in value:
        return value
    raw_images = value["images"]
    if not isinstance(raw_images, list):
        raise ValueError("content.images must be a list")
    if not raw_images:
        raise ValueError("content.images cannot be empty")
    if len(raw_images) > MAX_IMAGES_PER_EVENT:
        raise ValueError(f"content.images cannot contain more than {MAX_IMAGES_PER_EVENT} images")
    images = [ImageInput.model_validate(item) for item in raw_images]
    if sum(image.data_bytes for image in images) > MAX_TOTAL_IMAGE_BYTES:
        raise ValueError("inline image data exceeds the total size limit")
    normalized = dict(value)
    normalized["images"] = [image.model_dump() for image in images]
    return normalized


def _validate_content_size(value: str | dict[str, Any]) -> None:
    if isinstance(value, str):
        if len(value) > MAX_TEXT_CONTENT_CHARS:
            raise ValueError("content text exceeds the size limit")
        return
    text = value.get("text")
    if isinstance(text, str) and len(text) > MAX_TEXT_CONTENT_CHARS:
        raise ValueError("content text exceeds the size limit")
    try:
        encoded_size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
    except (TypeError, ValueError) as exc:
        raise ValueError("content must be JSON serializable") from exc
    if encoded_size > MAX_CONTENT_JSON_BYTES:
        raise ValueError("content exceeds the size limit")


def _data_image_size(value: str) -> int:
    match = _DATA_IMAGE_PATTERN.fullmatch(value)
    if match is None or match.group(1) not in _SUPPORTED_IMAGE_MEDIA_TYPES:
        raise ValueError("unsupported or malformed Base64 image data URL")
    try:
        decoded = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("malformed Base64 image data URL") from exc
    if not decoded:
        raise ValueError("inline image cannot be empty")
    if len(decoded) > MAX_IMAGE_BYTES:
        raise ValueError("inline image exceeds the per-image size limit")
    return len(decoded)


class TrustedEvent(BaseModel):
    """Normalized ingress with source, authority, and taint provenance."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_type: str
    content: str | dict[str, Any]
    source_type: SourceType
    source_identity: str | None = Field(default=None, max_length=255)
    conversation_id: str | None = Field(default=None, max_length=255)
    trust_level: TrustLevel
    authority_level: AuthorityLevel
    taint_labels: set[str] = Field(default_factory=set)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("content")
    @classmethod
    def validate_content_images(cls, value: str | dict[str, Any]) -> str | dict[str, Any]:
        return _validate_content_images(value)


class IngressEnvelope(BaseModel):
    """Information asserted by an authenticated platform adapter."""

    model_config = ConfigDict(extra="forbid")

    event_type: str = "message.received"
    content: str | dict[str, Any]
    source_type: SourceType
    source_identity: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=200)
    conversation_id: str | None = Field(default=None, max_length=255)
    authenticated: bool = False

    @field_validator("content")
    @classmethod
    def validate_content_images(cls, value: str | dict[str, Any]) -> str | dict[str, Any]:
        return _validate_content_images(value)
