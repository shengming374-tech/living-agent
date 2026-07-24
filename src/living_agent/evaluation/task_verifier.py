"""Independent arithmetic evidence verifier for the calculator slice."""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable

from pydantic import BaseModel, ValidationError

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
from living_agent.execution.work_contracts import (
    DAILY_PLAN_READ_CAPABILITY,
    DAILY_PLAN_UPDATE_CAPABILITY,
    DAILY_PLAN_WRITE_CAPABILITY,
    WEB_FETCH_CAPABILITY,
    WEB_SEARCH_CAPABILITY,
    WORKSPACE_LIST_CAPABILITY,
    WORKSPACE_READ_CAPABILITY,
    WORKSPACE_SEARCH_CAPABILITY,
    WORKSPACE_WRITE_CAPABILITY,
    DailyPlanReadArguments,
    DailyPlanUpdateArguments,
    DailyPlanWriteArguments,
    WebFetchArguments,
    WebSearchArguments,
    WorkspaceListArguments,
    WorkspaceReadArguments,
    WorkspaceSearchArguments,
    WorkspaceWriteArguments,
    daily_plan_scope_matches,
    web_fetch_scope,
    web_search_scope_matches,
    workspace_scope_matches,
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
            work_spec = self._work_spec(action.handler)
            if work_spec is not None:
                capability, operation, argument_model, scope_validator, requires_confirmation = (
                    work_spec
                )
                if request.capability != capability or request.operation != operation:
                    errors.append("work_action_mismatch")
                try:
                    work_arguments = argument_model.model_validate(request.arguments)
                except ValidationError:
                    errors.append("work_arguments_invalid")
                else:
                    if not scope_validator(work_arguments, request.resource_scope):
                        errors.append("work_scope_mismatch")
                if requires_confirmation and not proposal.task.confirmation_requirements:
                    errors.append("work_confirmation_missing")
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
            expected_work_evidence = {
                "workspace_read": "file_snapshot",
                "workspace_list": "directory_snapshot",
                "workspace_search": "workspace_search",
                "workspace_write": "file_commit",
                "web_fetch": "remote_response",
                "web_search": "remote_search_response",
                "daily_plan_read": "database_read",
                "daily_plan_write": "database_commit",
                "daily_plan_update": "database_commit",
            }.get(step.action.handler)
            if expected_work_evidence is not None and expected_work_evidence not in evidence_kinds:
                errors.append("work_evidence_missing")
            if result.errors:
                errors.append("completed_step_has_errors")
        return sorted(set(errors))

    @staticmethod
    def _work_spec(
        handler: str,
    ) -> tuple[str, str, type[BaseModel], Callable[[BaseModel, str], bool], bool] | None:
        specs: dict[
            str,
            tuple[str, str, type[BaseModel], Callable[[BaseModel, str], bool], bool],
        ] = {
            "workspace_read": (
                WORKSPACE_READ_CAPABILITY,
                "read",
                WorkspaceReadArguments,
                workspace_scope_matches,
                False,
            ),
            "workspace_list": (
                WORKSPACE_LIST_CAPABILITY,
                "list",
                WorkspaceListArguments,
                workspace_scope_matches,
                False,
            ),
            "workspace_search": (
                WORKSPACE_SEARCH_CAPABILITY,
                "search",
                WorkspaceSearchArguments,
                workspace_scope_matches,
                False,
            ),
            "workspace_write": (
                WORKSPACE_WRITE_CAPABILITY,
                "write",
                WorkspaceWriteArguments,
                workspace_scope_matches,
                True,
            ),
            "web_fetch": (
                WEB_FETCH_CAPABILITY,
                "read",
                WebFetchArguments,
                web_fetch_scope,
                False,
            ),
            "web_search": (
                WEB_SEARCH_CAPABILITY,
                "search",
                WebSearchArguments,
                web_search_scope_matches,
                False,
            ),
            "daily_plan_read": (
                DAILY_PLAN_READ_CAPABILITY,
                "read",
                DailyPlanReadArguments,
                daily_plan_scope_matches,
                False,
            ),
            "daily_plan_write": (
                DAILY_PLAN_WRITE_CAPABILITY,
                "write",
                DailyPlanWriteArguments,
                daily_plan_scope_matches,
                True,
            ),
            "daily_plan_update": (
                DAILY_PLAN_UPDATE_CAPABILITY,
                "update",
                DailyPlanUpdateArguments,
                daily_plan_scope_matches,
                True,
            ),
        }
        return specs.get(handler)
