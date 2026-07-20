"""The sole owner of user-visible language."""

from __future__ import annotations

import re

from living_agent.execution.contracts import (
    TaskRun,
    TaskRunStatus,
    TaskStepStatus,
    VerifiedTaskResult,
)
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

    def render_task_run(self, run: TaskRun) -> str:
        if run.status is TaskRunStatus.WAITING_CONFIRMATION:
            return (
                "The checked work is ready, but saving the report needs owner confirmation. "
                f"Task: {run.task.task_id}."
            )
        outputs = [
            result.output
            for result in run.step_results
            if result.status is TaskStepStatus.COMPLETED and result.output is not None
        ]
        calculations = [
            (output.get("expression"), output.get("value"))
            for output in outputs
            if "expression" in output and "value" in output
        ]
        report_saved = any("report_id" in output for output in outputs)
        if run.status is TaskRunStatus.COMPLETED and len(calculations) == 1 and not report_saved:
            expression, value = calculations[0]
            return f"I checked it: {expression} = {value}."
        if run.status is TaskRunStatus.COMPLETED and report_saved:
            return "I checked the task and saved its confirmed report."
        if run.status is TaskRunStatus.COMPLETED and calculations:
            summary = "; ".join(f"{expression} = {value}" for expression, value in calculations)
            return f"I checked them: {summary}."
        errors = {error for result in run.step_results for error in result.errors}
        single_calculator = (
            len(run.plan.steps) == 1 and run.plan.steps[0].action.handler == "calculator"
        )
        if single_calculator:
            if "plugin_timeout" in errors:
                return "I couldn't finish that calculation because the calculator timed out."
            if "plugin_crashed" in errors:
                return "I couldn't finish that calculation because the calculator stopped."
            return "I couldn't verify a reliable result for that calculation."
        if "plugin_timeout" in errors:
            return "I retried, but the task still timed out."
        if "plugin_crashed" in errors:
            return "I retried, but the task tool kept stopping."
        if "tainted_write_denied" in errors:
            return "I did not save that because its source was not safe for a write."
        return "I couldn't verify the task, so I stopped the remaining steps."

    def render_task_confirmation_denied(self) -> str:
        return "That write still needs confirmation from the owner."

    def render_task_confirmation_missing(self) -> str:
        return "I don't have a matching task waiting for confirmation here."

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
