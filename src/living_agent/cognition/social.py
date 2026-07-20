"""The sole owner of user-visible language."""

from __future__ import annotations

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
