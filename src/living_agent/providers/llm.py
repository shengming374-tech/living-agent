"""LLM provider protocol and deterministic test/development implementation."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict

from living_agent.cognition.context_compiler import CompiledContext, ContextKind


class ModelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    provider: str


class LLMProvider(Protocol):
    async def generate(self, context: CompiledContext) -> ModelResponse: ...


class MockLLMProvider:
    """Deterministic provider that makes the initial slice runnable without secrets."""

    async def generate(self, context: CompiledContext) -> ModelResponse:
        social = next(
            (
                section.content
                for section in context.sections
                if section.kind in {ContextKind.OWNER_REQUEST, ContextKind.SOCIAL_CHAT}
            ),
            "",
        )
        lowered = social.lower()
        if any(token in lowered for token in ("sad", "upset", "难过", "伤心")):
            text = "That sounds difficult. I'm here with you."
        elif any(token in lowered for token in ("hello", "hi", "你好")):
            text = "Hello. What is on your mind?"
        else:
            text = "I heard you. What would you like me to focus on?"
        return ModelResponse(text=text, provider="mock")
