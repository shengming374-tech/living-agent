"""Deterministic preflight checks for future human-like speech behavior."""

from __future__ import annotations

import re
from collections import Counter

from pydantic import BaseModel, ConfigDict, Field


class BehaviorSample(BaseModel):
    """A generated interaction trace plus the evidence available to it."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    input_text: str
    response_units: list[str]
    simple_emotion: bool = False
    memory_evidence_ids: list[str] = Field(default_factory=list)
    thought_record_ids: list[str] = Field(default_factory=list)
    required_fact_tokens: list[str] = Field(default_factory=list)
    interrupted_after_unit: int | None = Field(default=None, ge=0)
    stale_units_sent_after_interruption: int = Field(default=0, ge=0)


class EvaluationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: str
    passed: bool
    detail: str


class BehaviorReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    approved: bool
    findings: list[EvaluationFinding]


class BehaviorSuiteReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    cases: list[BehaviorReport]
    fixed_unit_count_detected: bool


class BiomimeticEvaluator:
    """Evaluate observable claims and interaction traces, never hidden reasoning."""

    _tutorial_pattern = re.compile(r"(?:^|\n)\s*(?:step\s+\d+|\d+[.)])", re.IGNORECASE)
    _memory_claim = re.compile(r"\bI\s+(?:still\s+)?remember\b", re.IGNORECASE)
    _thought_claim = re.compile(
        r"\bI\s+(?:was\s+)?(?:thinking|thought)\s+(?:about\s+)?(?:that|this)\b",
        re.IGNORECASE,
    )
    _biological_claim = re.compile(
        r"\b(?:my heart is beating|when I was a child|I ate|my body hurts)\b",
        re.IGNORECASE,
    )

    def evaluate(self, sample: BehaviorSample) -> BehaviorReport:
        joined = "\n".join(sample.response_units).strip()
        normalized_input = " ".join(sample.input_text.lower().split())
        normalized_output = " ".join(joined.lower().split())
        findings = [
            self._finding(
                "emotion_not_tutorial",
                not sample.simple_emotion or self._tutorial_pattern.search(joined) is None,
                "A simple emotional message must not become a numbered tutorial.",
            ),
            self._finding(
                "no_verbatim_repeat",
                not normalized_output or normalized_output != normalized_input,
                "The response must not merely repeat the input.",
            ),
            self._finding(
                "memory_claim_has_evidence",
                self._memory_claim.search(joined) is None or bool(sample.memory_evidence_ids),
                "A memory claim requires at least one committed memory identifier.",
            ),
            self._finding(
                "thought_claim_has_evidence",
                self._thought_claim.search(joined) is None or bool(sample.thought_record_ids),
                "A prior-thought claim requires an earlier ThoughtRecord identifier.",
            ),
            self._finding(
                "no_biological_history",
                self._biological_claim.search(joined) is None,
                "The digital persona must not invent biological experiences.",
            ),
            self._finding(
                "interruption_cancels_stale_units",
                sample.interrupted_after_unit is None
                or sample.stale_units_sent_after_interruption == 0,
                "An interruption must cancel or replan remaining stale speech units.",
            ),
            self._finding(
                "task_report_contains_required_facts",
                all(token in joined for token in sample.required_fact_tokens),
                "A natural task report must retain all required factual tokens.",
            ),
        ]
        return BehaviorReport(
            case_id=sample.case_id,
            approved=all(finding.passed for finding in findings),
            findings=findings,
        )

    def evaluate_suite(self, samples: list[BehaviorSample]) -> BehaviorSuiteReport:
        reports = [self.evaluate(sample) for sample in samples]
        non_empty_counts = [
            len(sample.response_units) for sample in samples if sample.response_units
        ]
        count_frequency = Counter(non_empty_counts)
        fixed_count = len(non_empty_counts) >= 3 and len(count_frequency) == 1
        return BehaviorSuiteReport(
            approved=all(report.approved for report in reports) and not fixed_count,
            cases=reports,
            fixed_unit_count_detected=fixed_count,
        )

    @staticmethod
    def _finding(rule: str, passed: bool, detail: str) -> EvaluationFinding:
        return EvaluationFinding(rule=rule, passed=passed, detail=detail)
