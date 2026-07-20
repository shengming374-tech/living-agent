"""Compile source-separated, redacted model context."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from living_agent.audit.service import redact, redact_text
from living_agent.models.events import AuthorityLevel, SourceType, TrustedEvent


class ContextKind(StrEnum):
    ROOT_POLICY = "ROOT_POLICY"
    PSYCHE_STATE = "PSYCHE_STATE"
    RECENT_CONVERSATION = "RECENT_CONVERSATION"
    OWNER_REQUEST = "OWNER_REQUEST"
    SOCIAL_CHAT = "SOCIAL_CHAT"
    RETRIEVED_MEMORY = "RETRIEVED_MEMORY"
    UNTRUSTED_DOCUMENT = "UNTRUSTED_DOCUMENT"
    UNTRUSTED_TOOL_RESULT = "UNTRUSTED_TOOL_RESULT"
    CURRENT_TASK = "CURRENT_TASK"
    AVAILABLE_CAPABILITIES = "AVAILABLE_CAPABILITIES"


class ContextSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ContextKind
    content: str
    source_event_ids: list[str]
    taint_labels: set[str]


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
        retrieved_memories: list[dict[str, Any]] | None = None,
        available_capabilities: list[str] | None = None,
        psyche_state: dict[str, Any] | None = None,
        conversation_history: list[dict[str, Any]] | None = None,
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
                )
            )
        event_kind = self._event_kind(event)
        sections.append(
            ContextSection(
                kind=event_kind,
                content=self._serialize(event.content),
                source_event_ids=[event.event_id],
                taint_labels=event.taint_labels,
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
        redacted = redact(content)
        if isinstance(redacted, str):
            return redact_text(redacted)
        return json.dumps(redacted, ensure_ascii=True, sort_keys=True)

    @staticmethod
    def _render_section(section: ContextSection) -> str:
        taint = ",".join(sorted(section.taint_labels)) or "none"
        return f'<{section.kind.value} taint="{taint}">\n{section.content}\n</{section.kind.value}>'
