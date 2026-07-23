"""MaiBot-inspired reply-necessity scheduling over host-owned conversation state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from living_agent.interaction.momentum import ConversationMomentum
from living_agent.models.conversation import TurnDecision, TurnScheduleDecision
from living_agent.models.events import SourceType, TrustedEvent


class ReplyNecessityEvaluator:
    """Decide whether to enter social planning without generating visible text."""

    def evaluate(
        self,
        event: TrustedEvent,
        momentum: ConversationMomentum,
        preliminary_turn: TurnDecision,
        *,
        pending_event_ids: list[str],
        cooldown_until: datetime | None,
    ) -> TurnScheduleDecision:
        now = event.created_at
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        if cooldown_until is not None and cooldown_until.tzinfo is None:
            cooldown_until = cooldown_until.replace(tzinfo=UTC)
        if event.source_type not in {SourceType.DIRECT_MESSAGE, SourceType.GROUP_MESSAGE}:
            return self._decision("suppress", 0.0, ["non_social_input"], pending_event_ids)

        mentions_agent = isinstance(event.content, dict) and bool(
            event.content.get("mentions_agent", False)
        )
        if event.source_type is SourceType.DIRECT_MESSAGE:
            reasons = ["direct_message"]
            if preliminary_turn.reason_code == "direct_question":
                reasons.append("direct_question")
            return self._decision(
                "trigger",
                1.0 if mentions_agent else 0.9,
                reasons,
                pending_event_ids,
            )
        if mentions_agent:
            return self._decision(
                "trigger", 1.0, ["explicit_mention", "forced_wakeup"], pending_event_ids
            )

        reason = preliminary_turn.reason_code
        if reason == "group_frequency_wait":
            pressure = min(0.65, 0.15 + momentum.user_turns_since_agent * 0.1)
            return self._decision(
                "wait",
                pressure,
                ["group_frequency_wait", "context_accumulating"],
                pending_event_ids,
            )
        if reason == "group_cooldown":
            delay = 0.0
            if cooldown_until is not None and cooldown_until > now:
                delay = (cooldown_until - now).total_seconds()
            return self._decision(
                "delay",
                0.3,
                ["agent_spoke_recently", "group_cooldown"],
                pending_event_ids,
                delay_seconds=delay,
            )
        if reason in {
            "group_addressed_to_other",
            "group_observation",
            "group_rate_skip",
            "group_tainted_observation",
        }:
            return self._decision("suppress", 0.1, [reason], pending_event_ids)
        return self._decision(
            "trigger",
            max(0.55, preliminary_turn.urgency),
            ["group_reply_necessity_satisfied"],
            pending_event_ids,
        )

    @staticmethod
    def apply(
        turn: TurnDecision,
        schedule: TurnScheduleDecision,
    ) -> TurnDecision:
        if schedule.action == "trigger":
            return turn.model_copy(
                update={"target_event_ids": schedule.pending_event_ids or turn.target_event_ids}
            )
        return TurnDecision(
            mode="observe",
            urgency=schedule.score,
            expected_units_min=0,
            expected_units_max=0,
            interruption_tolerance=1.0,
            target_event_ids=schedule.pending_event_ids or turn.target_event_ids,
            reason_code=turn.reason_code,
        )

    @staticmethod
    def _decision(
        action: Literal["trigger", "wait", "delay", "suppress"],
        score: float,
        reasons: list[str],
        pending_event_ids: list[str],
        *,
        delay_seconds: float | None = None,
    ) -> TurnScheduleDecision:
        return TurnScheduleDecision(
            action=action,
            score=score,
            reasons=reasons,
            pending_event_ids=pending_event_ids[-32:],
            delay_seconds=delay_seconds,
        )
