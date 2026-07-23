from pathlib import Path

import yaml

from living_agent.evaluation.biomimetic import BehaviorSample, BiomimeticEvaluator


def load_samples() -> list[BehaviorSample]:
    fixture = Path(__file__).parent / "fixtures" / "biomimetic_cases.yaml"
    payload = yaml.safe_load(fixture.read_text(encoding="utf-8"))
    return [BehaviorSample.model_validate(item) for item in payload]


def test_behavior_fixture_suite_is_grounded_and_varied() -> None:
    report = BiomimeticEvaluator().evaluate_suite(load_samples())

    assert report.approved
    assert not report.fixed_unit_count_detected


def test_unsupported_memory_thought_and_biological_claims_are_blocked() -> None:
    evaluator = BiomimeticEvaluator()
    sample = BehaviorSample(
        case_id="unsupported-claims",
        input_text="Tell me what happened.",
        response_units=[
            "I remember it. I was thinking about that. When I was a child, I ate there."
        ],
    )
    report = evaluator.evaluate(sample)
    failed_rules = {finding.rule for finding in report.findings if not finding.passed}

    assert not report.approved
    assert {
        "memory_claim_has_evidence",
        "thought_claim_has_evidence",
        "no_biological_history",
    } <= failed_rules


def test_interruption_and_fixed_unit_pattern_are_detected() -> None:
    evaluator = BiomimeticEvaluator()
    samples = [
        BehaviorSample(
            case_id=f"case-{index}",
            input_text="continue",
            response_units=["old unit", "another old unit", "last old unit"],
            interrupted_after_unit=1,
            stale_units_sent_after_interruption=2,
        )
        for index in range(3)
    ]
    report = evaluator.evaluate_suite(samples)

    assert not report.approved
    assert report.fixed_unit_count_detected
    assert all(not case.approved for case in report.cases)


def test_attention_and_schedule_require_grounded_visible_behavior() -> None:
    evaluator = BiomimeticEvaluator()
    report = evaluator.evaluate(
        BehaviorSample(
            case_id="ungrounded-social-runtime",
            input_text="继续",
            response_units=["我突然想到另一件事"],
            attention_cue_used=True,
            serious_context=True,
            schedule_action="wait",
            planning_superseded=True,
        )
    )
    failed = {finding.rule for finding in report.findings if not finding.passed}

    assert {
        "attention_drift_has_sources",
        "serious_context_suppresses_drift",
        "suppressed_schedule_has_no_output",
        "superseded_planning_has_no_output",
    } <= failed
