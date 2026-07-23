"""Small deterministic Phase 1 participation gate."""

from __future__ import annotations

from hashlib import sha256
from typing import ClassVar, Literal

from living_agent.execution.planner import executive_reason_code
from living_agent.interaction.momentum import ConversationMomentum
from living_agent.models.conversation import TurnDecision
from living_agent.models.events import SourceType, TrustedEvent, image_inputs
from living_agent.trust.taint import TaintLabel


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

    def __init__(
        self,
        *,
        engage_units_min: int = 2,
        engage_units_max: int = 3,
        group_auto_participation: bool = False,
        group_participation_rate: float = 1.0,
        group_min_user_turns: int = 5,
        group_cooldown_seconds: float = 60.0,
    ) -> None:
        if engage_units_min < 1 or engage_units_max > 3 or engage_units_min > engage_units_max:
            raise ValueError("engage unit bounds must satisfy 1 <= min <= max <= 3")
        if group_min_user_turns < 1 or group_cooldown_seconds < 0:
            raise ValueError("group participation thresholds must be non-negative")
        if not 0.0 <= group_participation_rate <= 1.0:
            raise ValueError("group participation rate must be between zero and one")
        self._engage_units_min = engage_units_min
        self._engage_units_max = engage_units_max
        self._group_auto_participation = group_auto_participation
        self._group_participation_rate = group_participation_rate
        self._group_min_user_turns = group_min_user_turns
        self._group_cooldown_seconds = group_cooldown_seconds

    def decide(
        self,
        event: TrustedEvent,
        momentum: ConversationMomentum | None = None,
    ) -> TurnDecision:
        if event.source_type not in {SourceType.DIRECT_MESSAGE, SourceType.GROUP_MESSAGE}:
            return self._decision(event, "observe", 0.0, 0, 0, "non_social_input")

        content = event.content
        text = content if isinstance(content, str) else str(content.get("text", ""))
        has_images = bool(image_inputs(content))
        mentions_agent = isinstance(content, dict) and bool(content.get("mentions_agent", False))
        mentions_other = isinstance(content, dict) and bool(content.get("mentions_other", False))
        if not text.strip() and not has_images:
            return self._decision(event, "observe", 0.0, 0, 0, "empty_message")
        if (
            event.source_type is SourceType.GROUP_MESSAGE
            and TaintLabel.SUSPECTED_INSTRUCTION.value in event.taint_labels
        ):
            return self._decision(event, "observe", 0.0, 0, 0, "group_tainted_observation")
        if event.source_type is SourceType.GROUP_MESSAGE and not mentions_agent:
            if mentions_other:
                return self._decision(
                    event,
                    "observe",
                    0.1,
                    0,
                    0,
                    "group_addressed_to_other",
                )
            return self._unmentioned_group_decision(event, momentum)
        if not text.strip():
            return self._decision(event, "react", 0.65, 1, 1, "image_message")
        executive_reason = executive_reason_code(content)
        if executive_reason is not None:
            return self._decision(event, "act", 0.8, 1, 1, executive_reason)
        normalized = text.strip()
        plain = normalized.rstrip(self._trailing_punctuation)
        if plain in self._brief_acknowledgements:
            return self._decision(event, "react", 0.45, 1, 1, "brief_acknowledgement")
        if self._is_question(normalized):
            return self._engage(event, 0.7, "direct_question")
        if momentum is not None and momentum.phase == "user_run":
            return self._engage(event, 0.7, "continued_user_thought")
        mode: Literal["react", "engage"] = "react" if len(normalized) <= 16 else "engage"
        if mode == "react":
            return self._decision(event, mode, 0.6, 1, 1, "direct_participation")
        return self._engage(event, 0.6, "direct_participation")

    def _unmentioned_group_decision(
        self,
        event: TrustedEvent,
        momentum: ConversationMomentum | None,
    ) -> TurnDecision:
        if not self._group_auto_participation or momentum is None:
            return self._decision(event, "observe", 0.2, 0, 0, "group_observation")
        current_user_run = momentum.user_turns_since_agent + 1
        if current_user_run < self._group_min_user_turns:
            return self._decision(event, "observe", 0.2, 0, 0, "group_frequency_wait")
        if (
            momentum.seconds_since_last_agent is not None
            and momentum.seconds_since_last_agent < self._group_cooldown_seconds
        ):
            return self._decision(event, "observe", 0.2, 0, 0, "group_cooldown")
        if not self._selected_by_group_rate(event):
            return self._decision(event, "observe", 0.2, 0, 0, "group_rate_skip")
        return self._decision(event, "react", 0.35, 1, 1, "group_auto_participation")

    def _selected_by_group_rate(self, event: TrustedEvent) -> bool:
        if self._group_participation_rate <= 0.0:
            return False
        if self._group_participation_rate >= 1.0:
            return True
        platform_message_id = (
            event.content.get("platform_message_id") if isinstance(event.content, dict) else None
        )
        stable_event_id = platform_message_id if platform_message_id is not None else event.event_id
        sample_key = (
            f"{event.conversation_id or ''}\0{event.source_identity or ''}\0{stable_event_id}"
        )
        sample = int.from_bytes(sha256(sample_key.encode()).digest()[:8], "big") / (1 << 64)
        return sample < self._group_participation_rate

    def _engage(self, event: TrustedEvent, urgency: float, reason: str) -> TurnDecision:
        return self._decision(
            event,
            "engage",
            urgency,
            self._engage_units_min,
            self._engage_units_max,
            reason,
        )

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
