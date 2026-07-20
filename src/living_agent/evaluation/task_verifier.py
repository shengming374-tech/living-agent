"""Independent arithmetic evidence verifier for the calculator slice."""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable

from pydantic import ValidationError

from living_agent.execution.contracts import (
    CALCULATOR_CAPABILITY,
    CALCULATOR_PLUGIN_ID,
    CALCULATOR_SCOPE,
    CalculatorOutput,
    TaskEvidence,
    TaskPlanProposal,
    TaskRun,
    TaskStepStatus,
    VerifiedTaskResult,
)
from living_agent.execution.report_contracts import TASK_REPORT_CAPABILITY, TaskReportArguments
from living_agent.models.tasks import TaskContract
from living_agent.plugins.rpc import PluginInvocationResult

Number = int | float
BinaryOperation = Callable[[Number, Number], Number]

_BINARY_OPERATIONS: dict[type[ast.operator], BinaryOperation] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATIONS: dict[type[ast.unaryop], Callable[[Number], Number]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class CalculatorTaskVerifier:
    def verify(
        self,
        *,
        task: TaskContract,
        requested_expression: str,
        plugin_result: PluginInvocationResult,
    ) -> VerifiedTaskResult:
        try:
            output = CalculatorOutput.model_validate(plugin_result.output)
        except ValidationError:
            return self._failure(task, "plugin_output_schema_invalid")
        if output.expression != requested_expression:
            return self._failure(task, "plugin_expression_mismatch")
        try:
            tree = ast.parse(requested_expression, mode="eval")
            if sum(1 for _ in ast.walk(tree)) > 64:
                raise ValueError("expression too complex")
            expected = self._evaluate(tree.body)
        except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
            return self._failure(task, "expression_verification_failed")
        if not self._numbers_equal(output.value, expected):
            return self._failure(task, "plugin_result_mismatch")
        return VerifiedTaskResult(
            task_id=task.task_id,
            success=True,
            output=output.model_dump(),
            evidence=[
                TaskEvidence(
                    kind="independent_calculation",
                    source="host_verifier",
                    data={
                        "plugin_id": plugin_result.plugin_id,
                        "expression": requested_expression,
                        "verified_value": expected,
                    },
                )
            ],
        )

    @classmethod
    def _evaluate(cls, node: ast.AST, *, nodes_left: int = 64) -> Number:
        if nodes_left <= 0:
            raise ValueError("expression too complex")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("non-numeric constant")
            return cls._bounded(node.value)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATIONS:
            value = _UNARY_OPERATIONS[type(node.op)](
                cls._evaluate(node.operand, nodes_left=nodes_left - 1)
            )
            return cls._bounded(value)
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATIONS:
            left = cls._evaluate(node.left, nodes_left=nodes_left - 1)
            right = cls._evaluate(node.right, nodes_left=nodes_left - 1)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("exponent too large")
            return cls._bounded(_BINARY_OPERATIONS[type(node.op)](left, right))
        raise ValueError("unsupported expression")

    @staticmethod
    def _bounded(value: Number) -> Number:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite result")
        if abs(value) > 1e100:
            raise ValueError("result too large")
        return value

    @staticmethod
    def _numbers_equal(actual: Number, expected: Number) -> bool:
        if isinstance(actual, int) and isinstance(expected, int):
            return actual == expected
        return math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-12)

    @staticmethod
    def _failure(task: TaskContract, code: str) -> VerifiedTaskResult:
        return VerifiedTaskResult(task_id=task.task_id, success=False, errors=[code])


class TaskPlanVerifier:
    """Validate plan authority boundaries and evidence-complete outcomes."""

    def validate(self, proposal: TaskPlanProposal) -> list[str]:
        errors: list[str] = []
        first_request = proposal.plan.steps[0].action.capability_request
        for step in proposal.plan.steps:
            action = step.action
            request = action.capability_request
            if request.actor_id != proposal.task.requester_id:
                errors.append("plan_actor_mismatch")
            if request.capability not in proposal.task.allowed_capabilities:
                errors.append("plan_capability_not_allowed")
            if (
                request.conversation_id != first_request.conversation_id
                or request.source_event_ids != first_request.source_event_ids
                or request.taint_labels != first_request.taint_labels
            ):
                errors.append("plan_provenance_mismatch")
            operation_name = f"{request.capability}.{request.operation}"
            if operation_name in proposal.task.forbidden_operations:
                errors.append("plan_operation_forbidden")
            if action.handler == "calculator" and (
                request.capability != CALCULATOR_CAPABILITY
                or request.operation != "execute"
                or request.resource_scope != CALCULATOR_SCOPE
                or action.plugin_id != CALCULATOR_PLUGIN_ID
                or action.plugin_operation != "calculate"
            ):
                errors.append("calculator_action_mismatch")
            if action.handler == "task_report" and (
                request.capability != TASK_REPORT_CAPABILITY
                or request.operation != "write"
                or not proposal.task.confirmation_requirements
            ):
                errors.append("task_report_action_mismatch")
            if action.handler == "task_report":
                try:
                    arguments = TaskReportArguments.model_validate(request.arguments)
                except ValidationError:
                    errors.append("task_report_arguments_invalid")
                else:
                    if (
                        arguments.task_id != proposal.task.task_id
                        or request.resource_scope != f"tasks/{proposal.task.task_id}/report"
                    ):
                        errors.append("task_report_scope_mismatch")
        return sorted(set(errors))

    @staticmethod
    def verify_completion(run: TaskRun) -> list[str]:
        errors: list[str] = []
        results = {result.step_id: result for result in run.step_results}
        for step in run.plan.steps:
            result = results.get(step.step_id)
            if result is None or result.status is not TaskStepStatus.COMPLETED:
                errors.append("task_step_incomplete")
                continue
            evidence_kinds = {item.kind for item in result.evidence}
            if step.action.handler == "calculator" and "independent_calculation" not in (
                evidence_kinds
            ):
                errors.append("calculator_evidence_missing")
            if step.action.handler == "task_report" and "database_commit" not in evidence_kinds:
                errors.append("task_report_evidence_missing")
            if result.errors:
                errors.append("completed_step_has_errors")
        return sorted(set(errors))
