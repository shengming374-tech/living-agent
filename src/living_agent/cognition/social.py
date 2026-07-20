"""The sole owner of user-visible language."""

from __future__ import annotations

from living_agent.execution.contracts import VerifiedTaskResult
from living_agent.interaction.turn_gate import TurnGate
from living_agent.models.conversation import TurnDecision
from living_agent.models.events import TrustedEvent


class SocialCognition:
    def __init__(self, turn_gate: TurnGate) -> None:
        self._turn_gate = turn_gate

    def decide_turn(self, event: TrustedEvent) -> TurnDecision:
        return self._turn_gate.decide(event)

    def render_model_text(self, text: str) -> str:
        """Return bounded model text; executive code never calls outbound adapters."""

        normalized = " ".join(text.strip().split())
        return normalized[:4000]

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
