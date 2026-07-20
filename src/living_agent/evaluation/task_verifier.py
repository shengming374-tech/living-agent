"""Independent arithmetic evidence verifier for the calculator slice."""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable

from pydantic import ValidationError

from living_agent.execution.contracts import (
    CalculatorOutput,
    TaskEvidence,
    VerifiedTaskResult,
)
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
