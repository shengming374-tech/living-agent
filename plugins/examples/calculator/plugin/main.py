"""Bounded arithmetic implementation for the isolated calculator process."""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable
from typing import Any

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
_MAX_NODES = 64
_MAX_ABSOLUTE_RESULT = 1e100
_MAX_EXPONENT = 12


def invoke(params: dict[str, Any]) -> dict[str, Any]:
    if set(params) != {"operation", "arguments"} or params["operation"] != "calculate":
        raise ValueError("unsupported calculator operation")
    arguments = params["arguments"]
    if not isinstance(arguments, dict) or set(arguments) != {"expression"}:
        raise ValueError("calculator arguments do not match the schema")
    expression = arguments["expression"]
    if not isinstance(expression, str) or not 1 <= len(expression) <= 200:
        raise ValueError("invalid expression")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > _MAX_NODES:
        raise ValueError("expression is too complex")
    value = _evaluate(tree.body)
    _require_bounded(value)
    return {"expression": expression.strip(), "value": value}


def _evaluate(node: ast.AST) -> Number:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("only numeric constants are allowed")
        _require_bounded(node.value)
        return node.value
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATIONS:
        value = _UNARY_OPERATIONS[type(node.op)](_evaluate(node.operand))
        _require_bounded(value)
        return value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATIONS:
        left = _evaluate(node.left)
        right = _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise ValueError("exponent is too large")
        value = _BINARY_OPERATIONS[type(node.op)](left, right)
        _require_bounded(value)
        return value
    raise ValueError("expression contains an unsupported operation")


def _require_bounded(value: Number) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("result must be finite")
    if abs(value) > _MAX_ABSOLUTE_RESULT:
        raise ValueError("result is too large")
