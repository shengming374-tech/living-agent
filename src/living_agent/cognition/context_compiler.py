"""Compile source-separated, redacted model context."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from living_agent.audit.service import redact, redact_text
from living_agent.models.events import (
    AuthorityLevel,
    ImageInput,
    SourceType,
    TrustedEvent,
    image_descriptors,
    image_inputs,
)

_MAX_HISTORY_IMAGES = 4
_MAX_HISTORY_IMAGE_BYTES = 20 * 1024 * 1024


class ContextKind(StrEnum):
    ROOT_POLICY = "ROOT_POLICY"
    PSYCHE_STATE = "PSYCHE_STATE"
    RECENT_CONVERSATION = "RECENT_CONVERSATION"
    SESSION_IMPRESSION = "SESSION_IMPRESSION"
    ATTENTION_CUE = "ATTENTION_CUE"
    INTERACTION_PLAN = "INTERACTION_PLAN"
    OWNER_REQUEST = "OWNER_REQUEST"
    SOCIAL_CHAT = "SOCIAL_CHAT"
    VISION_OBSERVATION = "VISION_OBSERVATION"
    RETRIEVED_MEMORY = "RETRIEVED_MEMORY"
    UNTRUSTED_DOCUMENT = "UNTRUSTED_DOCUMENT"
    UNTRUSTED_TOOL_RESULT = "UNTRUSTED_TOOL_RESULT"
    CURRENT_TASK = "CURRENT_TASK"
    AVAILABLE_CAPABILITIES = "AVAILABLE_CAPABILITIES"


class ContextImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(exclude=True, repr=False)
    detail: Literal["auto", "low", "high"] = "auto"
    source_event_id: str

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return ImageInput(url=value).url

    @classmethod
    def from_input(cls, image: ImageInput, *, source_event_id: str) -> ContextImage:
        return cls(
            url=image.url,
            detail=image.detail,
            source_event_id=source_event_id,
        )


class ContextSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ContextKind
    content: str
    source_event_ids: list[str]
    taint_labels: set[str]
    images: list[ContextImage] = Field(default_factory=list, max_length=4)


class CompiledContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: list[ContextSection]
    rendered: str


class ContextCompiler:
    """Keep policy, requests, memory, documents, and results in typed sections."""

    def compile(
        self,
        event: TrustedEvent,
        *,
        root_policy: str,
        current_task: dict[str, Any] | None = None,
        tool_results: list[dict[str, Any]] | None = None,
        retrieved_memories: list[dict[str, Any]] | None = None,
        available_capabilities: list[str] | None = None,
        psyche_state: dict[str, Any] | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
        interaction_plan: dict[str, Any] | None = None,
        session_impression: dict[str, Any] | None = None,
        attention_cue: dict[str, Any] | None = None,
    ) -> CompiledContext:
        sections = [
            ContextSection(
                kind=ContextKind.ROOT_POLICY,
                content=root_policy,
                source_event_ids=[],
                taint_labels=set(),
            )
        ]
        if psyche_state is not None:
            sections.append(
                ContextSection(
                    kind=ContextKind.PSYCHE_STATE,
                    content=self._serialize(psyche_state),
                    source_event_ids=[event.event_id],
                    taint_labels=set(event.taint_labels) | {"host_derived_state"},
                )
            )
        if conversation_history:
            history_source_ids = [
                str(item["event_id"])
                for item in conversation_history
                if item.get("event_id") is not None
            ]
            history_taint: set[str] = set()
            for item in conversation_history:
                history_taint.update(str(label) for label in item.get("taint_labels", []))
            sections.append(
                ContextSection(
                    kind=ContextKind.RECENT_CONVERSATION,
                    content=self._serialize(conversation_history),
                    source_event_ids=history_source_ids,
                    taint_labels=history_taint | {"conversation_history"},
                    images=self._history_images(conversation_history),
                )
            )
        if session_impression is not None:
            sections.append(
                ContextSection(
                    kind=ContextKind.SESSION_IMPRESSION,
                    content=self._serialize(session_impression),
                    source_event_ids=[
                        str(item) for item in session_impression.get("source_event_ids", [])
                    ],
                    taint_labels={
                        "host_derived_state",
                        "session_impression",
                        "conversation_history",
                        "derived_from_external",
                    },
                )
            )
        if attention_cue is not None:
            sections.append(
                ContextSection(
                    kind=ContextKind.ATTENTION_CUE,
                    content=self._serialize(attention_cue),
                    source_event_ids=[
                        str(item) for item in attention_cue.get("source_event_ids", [])
                    ],
                    taint_labels={
                        "host_derived_state",
                        "attention_cue",
                        "conversation_history",
                        "derived_from_external",
                    },
                )
            )
        if interaction_plan is not None:
            sections.append(
                ContextSection(
                    kind=ContextKind.INTERACTION_PLAN,
                    content=self._serialize(interaction_plan),
                    source_event_ids=[event.event_id],
                    taint_labels={"host_interaction_plan"},
                )
            )
        event_kind = self._event_kind(event)
        sections.append(
            ContextSection(
                kind=event_kind,
                content=self._serialize(event.content),
                source_event_ids=[event.event_id],
                taint_labels=event.taint_labels,
                images=self._context_images(event.content, source_event_id=event.event_id),
            )
        )
        for memory in retrieved_memories or []:
            sections.append(
                ContextSection(
                    kind=ContextKind.RETRIEVED_MEMORY,
                    content=self._serialize(memory),
                    source_event_ids=[str(item) for item in memory.get("source_event_ids", [])],
                    taint_labels={"retrieved_memory"},
                )
            )
        if current_task is not None:
            sections.append(
                ContextSection(
                    kind=ContextKind.CURRENT_TASK,
                    content=self._serialize(current_task),
                    source_event_ids=[event.event_id],
                    taint_labels=set(event.taint_labels),
                )
            )
        for result in tool_results or []:
            source_event_ids = [str(item) for item in result.get("source_event_ids", [])]
            supplied_taint = result.get("taint_labels", [])
            taint_labels = (
                {str(item) for item in supplied_taint}
                if isinstance(supplied_taint, list)
                else set()
            )
            sections.append(
                ContextSection(
                    kind=ContextKind.UNTRUSTED_TOOL_RESULT,
                    content=self._serialize(result),
                    source_event_ids=source_event_ids or [event.event_id],
                    taint_labels=taint_labels | {"untrusted_tool_result"},
                )
            )
        sections.append(
            ContextSection(
                kind=ContextKind.AVAILABLE_CAPABILITIES,
                content=self._serialize(available_capabilities or []),
                source_event_ids=[],
                taint_labels=set(),
            )
        )
        rendered = "\n\n".join(self._render_section(section) for section in sections)
        return CompiledContext(sections=sections, rendered=rendered)

    @staticmethod
    def _event_kind(event: TrustedEvent) -> ContextKind:
        if event.source_type in {SourceType.WEBPAGE, SourceType.FILE}:
            return ContextKind.UNTRUSTED_DOCUMENT
        if event.source_type in {SourceType.TOOL_RESULT, SourceType.PLUGIN_RESULT}:
            return ContextKind.UNTRUSTED_TOOL_RESULT
        if event.authority_level is AuthorityLevel.OWNER:
            return ContextKind.OWNER_REQUEST
        return ContextKind.SOCIAL_CHAT

    @staticmethod
    def _serialize(content: Any) -> str:
        redacted = redact(ContextCompiler._without_image_payloads(content))
        if isinstance(redacted, str):
            return redact_text(redacted)
        return json.dumps(redacted, ensure_ascii=True, sort_keys=True)

    @staticmethod
    def _context_images(
        content: str | dict[str, Any],
        *,
        source_event_id: str,
    ) -> list[ContextImage]:
        return [
            ContextImage.from_input(image, source_event_id=source_event_id)
            for image in image_inputs(content)
        ]

    @classmethod
    def _history_images(cls, history: list[dict[str, Any]]) -> list[ContextImage]:
        images_with_sizes: list[tuple[ContextImage, int]] = []
        for item in history:
            content = item.get("content")
            event_id = item.get("event_id")
            if not isinstance(content, (str, dict)) or event_id is None:
                continue
            inputs = image_inputs(content)
            images_with_sizes.extend(
                (
                    ContextImage.from_input(image, source_event_id=str(event_id)),
                    image.data_bytes,
                )
                for image in inputs
            )
        selected: list[ContextImage] = []
        inline_bytes = 0
        for image, data_bytes in reversed(images_with_sizes):
            if len(selected) >= _MAX_HISTORY_IMAGES:
                break
            if data_bytes and inline_bytes + data_bytes > _MAX_HISTORY_IMAGE_BYTES:
                continue
            selected.append(image)
            inline_bytes += data_bytes
        selected.reverse()
        return selected

    @staticmethod
    def _without_image_payloads(content: Any) -> Any:
        if isinstance(content, dict):
            sanitized: dict[str, Any] = {}
            for key, value in content.items():
                if str(key) == "images" and isinstance(value, list):
                    sanitized[str(key)] = image_descriptors({"images": value})
                else:
                    sanitized[str(key)] = ContextCompiler._without_image_payloads(value)
            return sanitized
        if isinstance(content, list):
            return [ContextCompiler._without_image_payloads(item) for item in content]
        if isinstance(content, tuple):
            return [ContextCompiler._without_image_payloads(item) for item in content]
        return content

    @staticmethod
    def _render_section(section: ContextSection) -> str:
        taint = ",".join(sorted(section.taint_labels)) or "none"
        return (
            f'<{section.kind.value} taint="{taint}" images="{len(section.images)}">\n'
            f"{section.content}\n</{section.kind.value}>"
        )
