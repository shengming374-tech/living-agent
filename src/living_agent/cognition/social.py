"""The sole owner of user-visible language."""

from __future__ import annotations

import re

from living_agent.execution.contracts import VerifiedTaskResult
from living_agent.interaction.momentum import ConversationMomentum
from living_agent.interaction.turn_gate import TurnGate
from living_agent.models.conversation import SpeechUnit, TurnDecision, UtteranceSession
from living_agent.models.events import TrustedEvent


class SocialCognition:
    def __init__(self, turn_gate: TurnGate) -> None:
        self._turn_gate = turn_gate

    def decide_turn(
        self,
        event: TrustedEvent,
        momentum: ConversationMomentum | None = None,
    ) -> TurnDecision:
        return self._turn_gate.decide(event, momentum)

    def render_model_text(self, text: str) -> str:
        """Return bounded model text; executive code never calls outbound adapters."""

        normalized = " ".join(text.strip().split())
        return normalized[:4000]

    def plan_utterance(self, text: str, turn: TurnDecision) -> UtteranceSession:
        units = self._semantic_units(text, maximum=max(1, turn.expected_units_max))
        if turn.mode == "react":
            units = units[:1]
        speech_units = [
            SpeechUnit(
                function="reaction" if index == 0 else "continuation",
                text=unit,
                delay_min_ms=0 if index == 0 else 300,
                delay_max_ms=0 if index == 0 else 650,
                cancellable=index > 0,
            )
            for index, unit in enumerate(units)
        ]
        return UtteranceSession(
            intention=turn.reason_code,
            units=speech_units,
            interruption_policy="cancel_unsent_on_new_message",
        )

    def render_task_result(self, result: VerifiedTaskResult) -> str:
        if result.success and result.output is not None:
            expression = result.output.get("expression")
            value = result.output.get("value")
            return f"I checked it: {expression} = {value}."
        if "plugin_timeout" in result.errors:
            return "I couldn't finish that calculation because the calculator timed out."
        if "plugin_crashed" in result.errors:
            return "I couldn't finish that calculation because the calculator stopped."
        return "I couldn't verify a reliable result for that calculation."

    def render_continuity_block(self) -> str:
        return "I don't have a record that supports saying that."

    def render_model_failure(self) -> str:
        return "I couldn't reach my language model just now."

    @staticmethod
    def _semantic_units(text: str, *, maximum: int) -> list[str]:
        lines = [" ".join(line.split()) for line in text.strip().splitlines() if line.strip()]
        if len(lines) == 1:
            sentences = [
                item.strip()
                for item in re.findall(
                    r"[^\u3002\uFF01\uFF1F!?]+[\u3002\uFF01\uFF1F!?]?",
                    lines[0],
                )
                if item.strip()
            ]
            if len(sentences) > 1:
                lines = sentences
        normalized = [line[:120].strip() for line in lines if line.strip()]
        if not normalized:
            normalized = ["..."]
        if maximum == 1:
            return normalized[:1]
        if len(normalized) <= maximum:
            return normalized
        head = normalized[: maximum - 1]
        tail = " ".join(normalized[maximum - 1 :])[:120].strip()
        return [*head, tail]
