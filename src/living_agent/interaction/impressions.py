"""Sourced mid-term conversation impressions with deterministic fallback."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from living_agent.audit.service import AuditService, redact_text
from living_agent.cognition.context_compiler import (
    CompiledContext,
    ContextKind,
    ContextSection,
)
from living_agent.interaction.social_state import SocialStateRepository
from living_agent.models.conversation import AttentionCue, SessionImpression
from living_agent.models.events import SourceType, TrustedEvent
from living_agent.providers.llm import LLMProvider, LLMProviderError


class _ImpressionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=1200)
    topics: list[str] = Field(default_factory=list, max_length=8)
    unresolved_threads: list[str] = Field(default_factory=list, max_length=6)
    emotional_tone: str = Field(min_length=1, max_length=80)
    participant_cues: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(ge=0.0, le=1.0)


class SessionImpressionService:
    def __init__(
        self,
        *,
        repository: SocialStateRepository,
        llm: LLMProvider,
        audit: AuditService,
        min_events: int,
        ttl_hours: float,
    ) -> None:
        self._repository = repository
        self._llm = llm
        self._audit = audit
        self._min_events = min_events
        self._ttl = timedelta(hours=ttl_hours)

    async def consider(
        self,
        conversation_id: str,
        events: list[TrustedEvent],
        *,
        now: datetime,
    ) -> SessionImpression | None:
        social_events = [
            event
            for event in events
            if event.conversation_id == conversation_id
            and event.source_type
            in {
                SourceType.DIRECT_MESSAGE,
                SourceType.GROUP_MESSAGE,
                SourceType.AGENT_MESSAGE,
            }
        ][-64:]
        latest = await self._repository.latest_impression(conversation_id, now=now)
        covered = set(latest.source_event_ids) if latest is not None else set()
        new_events = [event for event in social_events if event.event_id not in covered]
        if len(new_events) < self._min_events:
            return latest

        selected = social_events[-24:]
        mode = "model"
        try:
            payload = await self._model_payload(selected)
        except (LLMProviderError, ValidationError, ValueError, json.JSONDecodeError):
            payload = self._fallback_payload(selected)
            mode = "deterministic_fallback"
        target = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
        impression = SessionImpression(
            conversation_id=conversation_id,
            summary=payload.summary,
            topics=payload.topics,
            unresolved_threads=payload.unresolved_threads,
            emotional_tone=payload.emotional_tone,
            participant_cues=payload.participant_cues,
            source_event_ids=[event.event_id for event in selected],
            confidence=payload.confidence,
            created_at=target,
            expires_at=target + self._ttl,
        )
        saved = await self._repository.save_impression(impression)
        await self._audit.append(
            action="session_impression.created",
            actor_id="living-agent",
            conversation_id=conversation_id,
            outcome=mode,
            details={
                "impression_id": saved.impression_id,
                "source_event_ids": saved.source_event_ids,
                "topic_count": len(saved.topics),
                "unresolved_count": len(saved.unresolved_threads),
                "confidence": saved.confidence,
            },
        )
        return saved

    async def _model_payload(self, events: list[TrustedEvent]) -> _ImpressionPayload:
        history = [self._event_payload(event) for event in events]
        policy = (
            "Create a compact conversation impression as strict JSON with keys summary, topics, "
            "unresolved_threads, emotional_tone, participant_cues, confidence. Do not infer facts, "
            "relationships, permissions, memories, or hidden thoughts. Use only the supplied "
            "events."
        )
        sections = [
            ContextSection(
                kind=ContextKind.ROOT_POLICY,
                content=policy,
                source_event_ids=[],
                taint_labels=set(),
            ),
            ContextSection(
                kind=ContextKind.RECENT_CONVERSATION,
                content=json.dumps(history, ensure_ascii=True, sort_keys=True),
                source_event_ids=[event.event_id for event in events],
                taint_labels={"conversation_history", "summary_input"},
            ),
        ]
        response = await self._llm.generate(
            CompiledContext(
                sections=sections,
                rendered="\n\n".join(
                    f"<{section.kind.value}>\n{section.content}\n</{section.kind.value}>"
                    for section in sections
                ),
            )
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
        return _ImpressionPayload.model_validate(json.loads(raw))

    @classmethod
    def _fallback_payload(cls, events: list[TrustedEvent]) -> _ImpressionPayload:
        user_texts = [
            cls._event_text(event)
            for event in events
            if event.source_type in {SourceType.DIRECT_MESSAGE, SourceType.GROUP_MESSAGE}
            and cls._event_text(event)
        ]
        excerpts: list[str] = []
        for text in user_texts[-6:]:
            excerpt = re.split("[\u3002\uff01\uff1f!?\uff1b;\n]", text, maxsplit=1)[0]
            excerpt = excerpt.strip()[:80]
            if excerpt and excerpt not in excerpts:
                excerpts.append(excerpt)
        unresolved = [
            text[:120]
            for text in user_texts[-8:]
            if any(marker in text for marker in ("?", "\uff1f", "还没", "以后", "下次", "回头"))
        ][-6:]
        joined = " ".join(user_texts[-8:])
        if any(token in joined for token in ("难过", "伤心", "害怕", "焦虑", "生气")):
            tone = "serious_or_low"
        elif any(token in joined for token in ("哈哈", "开心", "好耶", "有趣", "惊喜")):
            tone = "light_or_positive"
        else:
            tone = "neutral"
        summary = "\uff1b".join(excerpts[-4:]) or "这段会话暂时没有形成稳定主题"
        return _ImpressionPayload(
            summary=summary[:1200],
            topics=excerpts[-8:],
            unresolved_threads=unresolved,
            emotional_tone=tone,
            participant_cues=[],
            confidence=0.45,
        )

    @classmethod
    def _event_payload(cls, event: TrustedEvent) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "role": "assistant" if event.source_type is SourceType.AGENT_MESSAGE else "user",
            "source_identity": event.source_identity,
            "text": cls._event_text(event),
        }

    @staticmethod
    def _event_text(event: TrustedEvent) -> str:
        content = event.content
        text = content if isinstance(content, str) else content.get("text", "")
        return redact_text(" ".join(text.split())[:1200]) if isinstance(text, str) else ""


class AttentionCueService:
    _SERIOUS = re.compile(r"难过|伤心|害怕|焦虑|生气|冲突|去世|自杀|痛苦|求助")

    def __init__(
        self,
        *,
        repository: SocialStateRepository,
        ttl_minutes: float,
    ) -> None:
        self._repository = repository
        self._ttl = timedelta(minutes=ttl_minutes)

    async def consider(
        self,
        event: TrustedEvent,
        impression: SessionImpression | None,
        recent_events: list[TrustedEvent],
    ) -> AttentionCue | None:
        if event.conversation_id is None or impression is None:
            return None
        text = SessionImpressionService._event_text(event)
        if not text or self._SERIOUS.search(text) or text.endswith(("?", "\uff1f")):
            return None
        now = (
            event.created_at
            if event.created_at.tzinfo is not None
            else event.created_at.replace(tzinfo=UTC)
        )
        latest = await self._repository.latest_cue(
            event.conversation_id, now=now, include_used=True
        )
        for topic in reversed(impression.topics):
            normalized_topic = " ".join(topic.split())[:200]
            if not self._related(normalized_topic, text):
                continue
            if latest is not None and latest.topic == normalized_topic:
                return None
            impression_sources = set(impression.source_event_ids)
            sources = [
                prior.event_id
                for prior in recent_events
                if prior.event_id != event.event_id
                and prior.event_id in impression_sources
                and self._related(
                    normalized_topic,
                    SessionImpressionService._event_text(prior),
                )
            ][-31:]
            if not sources:
                return None
            cue = AttentionCue(
                conversation_id=event.conversation_id,
                cue_text=f"当前消息重新碰到了近期线索\uff1a{normalized_topic}",
                topic=normalized_topic,
                source_event_ids=[*sources, event.event_id],
                salience=0.55,
                created_at=now,
                expires_at=now + self._ttl,
            )
            return await self._repository.save_cue(cue)
        return None

    @staticmethod
    def _related(topic: str, text: str) -> bool:
        topic_folded = topic.casefold()
        text_folded = text.casefold()
        latin = re.findall(r"[a-z0-9]{3,}", topic_folded)
        if any(token in text_folded for token in latin):
            return True
        chinese_runs = re.findall(r"[\u4e00-\u9fff]{2,}", topic)
        bigrams = {
            run[index : index + 2]
            for run in chinese_runs
            for index in range(len(run) - 1)
        }
        return any(token in text for token in bigrams)
