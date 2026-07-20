"""Small deterministic Phase 1 participation gate."""

from __future__ import annotations

from typing import ClassVar, Literal

from living_agent.execution.contracts import extract_calculation_expression
from living_agent.interaction.momentum import ConversationMomentum
from living_agent.models.conversation import TurnDecision
from living_agent.models.events import SourceType, TrustedEvent


class TurnGate:
    _brief_acknowledgements: ClassVar[frozenset[str]] = frozenset(
        {
            "嗯",
            "嗯嗯",
            "好",
            "好的",
            "行",
            "可以",
            "哈哈",
            "哈哈哈",
            "确实",
            "没错",
            "知道了",
            "收到",
        }
    )
    _trailing_punctuation: ClassVar[str] = "\u3002\uff01!\uff1f?~\uff5e "

    def decide(
        self,
        event: TrustedEvent,
        momentum: ConversationMomentum | None = None,
    ) -> TurnDecision:
        if event.source_type not in {SourceType.DIRECT_MESSAGE, SourceType.GROUP_MESSAGE}:
            return self._decision(event, "observe", 0.0, 0, 0, "non_social_input")

        content = event.content
        text = content if isinstance(content, str) else str(content.get("text", ""))
        mentions_agent = isinstance(content, dict) and bool(content.get("mentions_agent", False))
        if not text.strip():
            return self._decision(event, "observe", 0.0, 0, 0, "empty_message")
        if event.source_type is SourceType.GROUP_MESSAGE and not mentions_agent:
            return self._decision(event, "observe", 0.2, 0, 0, "group_observation")
        if extract_calculation_expression(content) is not None:
            return self._decision(event, "act", 0.8, 1, 1, "calculator_task")
        normalized = text.strip()
        plain = normalized.rstrip(self._trailing_punctuation)
        if plain in self._brief_acknowledgements:
            return self._decision(event, "react", 0.45, 1, 1, "brief_acknowledgement")
        if self._is_question(normalized):
            return self._decision(event, "engage", 0.7, 2, 3, "direct_question")
        if momentum is not None and momentum.phase == "user_run":
            return self._decision(event, "engage", 0.7, 2, 3, "continued_user_thought")
        mode: Literal["react", "engage"] = "react" if len(normalized) <= 16 else "engage"
        if mode == "react":
            return self._decision(event, mode, 0.6, 1, 1, "direct_participation")
        return self._decision(event, mode, 0.6, 2, 3, "direct_participation")

    @staticmethod
    def _is_question(text: str) -> bool:
        if len(text.rstrip(TurnGate._trailing_punctuation)) < 4:
            return False
        return text.endswith(("?", "\uff1f")) or any(
            marker in text for marker in ("为什么", "怎么", "觉得呢", "怎么办", "是不是")
        )

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
