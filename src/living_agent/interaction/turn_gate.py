"""Small deterministic Phase 1 participation gate."""

from __future__ import annotations

from typing import Literal

from living_agent.models.conversation import TurnDecision
from living_agent.models.events import SourceType, TrustedEvent


class TurnGate:
    def decide(self, event: TrustedEvent) -> TurnDecision:
        if event.source_type not in {SourceType.DIRECT_MESSAGE, SourceType.GROUP_MESSAGE}:
            return self._decision(event, "observe", 0.0, 0, 0, "non_social_input")

        content = event.content
        text = content if isinstance(content, str) else str(content.get("text", ""))
        mentions_agent = isinstance(content, dict) and bool(content.get("mentions_agent", False))
        if not text.strip():
            return self._decision(event, "observe", 0.0, 0, 0, "empty_message")
        if event.source_type is SourceType.GROUP_MESSAGE and not mentions_agent:
            return self._decision(event, "observe", 0.2, 0, 0, "group_observation")
        mode: Literal["react", "engage"] = "react" if len(text.strip()) <= 16 else "engage"
        return self._decision(event, mode, 0.6, 1, 1, "direct_participation")

    @staticmethod
    def _decision(
        event: TrustedEvent,
        mode: Literal["observe", "react", "engage", "act"],
        urgency: float,
        minimum: int,
        maximum: int,
        reason: str,
    ) -> TurnDecision:
        return TurnDecision(
            mode=mode,
            urgency=urgency,
            expected_units_min=minimum,
            expected_units_max=maximum,
            interruption_tolerance=0.8 if mode != "observe" else 1.0,
            target_event_ids=[event.event_id],
            reason_code=reason,
        )
