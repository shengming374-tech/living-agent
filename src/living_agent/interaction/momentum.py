"""Deterministic recent-conversation momentum derived from trusted events."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from living_agent.models.events import SourceType, TrustedEvent


class ConversationMomentum(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phase: Literal["new", "back_and_forth", "user_run"]
    recent_turn_count: int = Field(ge=0, le=128)
    agent_spoke_last: bool
    user_turns_since_agent: int = Field(ge=0, le=128)
    recent_agent_unit_count: int = Field(ge=0, le=3)
    seconds_since_last_agent: float | None = Field(default=None, ge=0.0)

    @classmethod
    def from_history(
        cls,
        history: list[TrustedEvent],
        *,
        now: datetime,
        active_window: timedelta = timedelta(minutes=10),
    ) -> ConversationMomentum:
        cutoff = now - active_window

        def is_active(event: TrustedEvent) -> bool:
            created_at = event.created_at
            if created_at.tzinfo is None and cutoff.tzinfo is not None:
                created_at = created_at.replace(tzinfo=cutoff.tzinfo)
            return created_at >= cutoff

        bounded_history = history[-128:]
        last_agent = next(
            (
                event
                for event in reversed(bounded_history)
                if event.source_type is SourceType.AGENT_MESSAGE
            ),
            None,
        )
        seconds_since_last_agent = None
        if last_agent is not None:
            last_agent_at = last_agent.created_at
            if last_agent_at.tzinfo is None and now.tzinfo is not None:
                last_agent_at = last_agent_at.replace(tzinfo=now.tzinfo)
            seconds_since_last_agent = max(0.0, (now - last_agent_at).total_seconds())

        recent = [
            event
            for event in bounded_history
            if is_active(event)
            and event.source_type
            in {
                SourceType.DIRECT_MESSAGE,
                SourceType.GROUP_MESSAGE,
                SourceType.AGENT_MESSAGE,
            }
        ]
        if not recent:
            return cls(
                phase="new",
                recent_turn_count=0,
                agent_spoke_last=False,
                user_turns_since_agent=0,
                recent_agent_unit_count=0,
                seconds_since_last_agent=seconds_since_last_agent,
            )

        agent_spoke_last = recent[-1].source_type is SourceType.AGENT_MESSAGE
        user_turns_since_agent = 0
        for event in reversed(recent):
            if event.source_type is SourceType.AGENT_MESSAGE:
                break
            user_turns_since_agent += 1

        recent_last_agent = next(
            (event for event in reversed(recent) if event.source_type is SourceType.AGENT_MESSAGE),
            None,
        )
        recent_agent_unit_count = 0
        if recent_last_agent is not None:
            content = recent_last_agent.content
            text = content if isinstance(content, str) else str(content.get("text", ""))
            session_id = content.get("utterance_session_id") if isinstance(content, dict) else None
            if isinstance(session_id, str) and session_id:
                recent_agent_unit_count = min(
                    3,
                    sum(
                        1
                        for event in reversed(recent)
                        if event.source_type is SourceType.AGENT_MESSAGE
                        and isinstance(event.content, dict)
                        and event.content.get("utterance_session_id") == session_id
                    ),
                )
            else:
                recent_agent_unit_count = min(3, len([line for line in text.splitlines() if line]))

        return cls(
            phase="back_and_forth" if agent_spoke_last else "user_run",
            recent_turn_count=len(recent),
            agent_spoke_last=agent_spoke_last,
            user_turns_since_agent=user_turns_since_agent,
            recent_agent_unit_count=recent_agent_unit_count,
            seconds_since_last_agent=seconds_since_last_agent,
        )
