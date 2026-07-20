from typing import Any

import pytest
from pydantic import ValidationError

from living_agent.evaluation.task_verifier import CalculatorTaskVerifier
from living_agent.execution.contracts import VerifiedTaskResult
from living_agent.models.tasks import TaskContract
from living_agent.plugins.rpc import PluginInvocationResult


def make_task() -> TaskContract:
    return TaskContract(
        requester_id="member-1",
        goal="Calculate 2 + 2",
        constraints=["calculator only"],
        allowed_capabilities=["calculator.evaluate"],
        forbidden_operations=["filesystem.write"],
        success_criteria=["verified numeric result"],
        confirmation_requirements=[],
    )


def test_task_contract_validates_and_rejects_duplicates() -> None:
    task = make_task()
    assert task.task_id
    assert task.requester_id == "member-1"

    with pytest.raises(ValidationError):
        TaskContract(
            requester_id="member-1",
            goal="duplicate constraints",
            constraints=["same", "same"],
            allowed_capabilities=[],
            forbidden_operations=[],
            success_criteria=["done"],
            confirmation_requirements=[],
        )


@pytest.mark.parametrize(
    ("output", "error"),
    [
        ({"expression": "2 + 2", "value": 5}, "plugin_result_mismatch"),
        ({"expression": "3 + 2", "value": 4}, "plugin_expression_mismatch"),
        ({"expression": "2 + 2", "value": "success"}, "plugin_output_schema_invalid"),
    ],
)
def test_verifier_rejects_forged_or_invalid_plugin_success(
    output: dict[str, Any],
    error: str,
) -> None:
    result: VerifiedTaskResult = CalculatorTaskVerifier().verify(
        task=make_task(),
        requested_expression="2 + 2",
        plugin_result=PluginInvocationResult(
            plugin_id="test.fake",
            operation="calculate",
            output=output,
        ),
    )

    assert not result.success
    assert result.errors == [error]
