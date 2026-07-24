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
    def __init__(
        self,
        turn_gate: TurnGate,
        *,
        followup_delay_min_ms: int = 300,
        followup_delay_max_ms: int = 650,
        avoid_full_stops: bool = False,
    ) -> None:
        if (
            followup_delay_min_ms < 0
            or followup_delay_min_ms > followup_delay_max_ms
            or followup_delay_max_ms > 10000
        ):
            raise ValueError("follow-up delay bounds must be ordered and non-negative")
        self._turn_gate = turn_gate
        self._followup_delay_min_ms = followup_delay_min_ms
        self._followup_delay_max_ms = followup_delay_max_ms
        self._avoid_full_stops = avoid_full_stops

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
        units = self._semantic_units(
            text,
            maximum=max(1, turn.expected_units_max),
            unit_chars=1200 if turn.mode == "act" else 120,
        )
        if turn.mode == "react":
            units = units[:1]
        if self._avoid_full_stops:
            units = [self._without_sentence_full_stops(unit) for unit in units]
        speech_units = [
            SpeechUnit(
                function=(
                    "task_result"
                    if index == 0 and turn.mode == "act"
                    else "reaction"
                    if index == 0
                    else "continuation"
                ),
                text=unit,
                delay_min_ms=0 if index == 0 else self._followup_delay_min_ms,
                delay_max_ms=0 if index == 0 else self._followup_delay_max_ms,
                cancellable=index > 0,
            )
            for index, unit in enumerate(units)
        ]
        return UtteranceSession(
            intention=turn.reason_code,
            units=speech_units,
            interruption_policy="cancel_unsent_on_new_message",
        )

    @staticmethod
    def _without_sentence_full_stops(text: str) -> str:
        normalized = re.sub(r"[。.](?=\s|$)", "", text).strip()
        return normalized or text.strip()

    def render_task_result(self, result: VerifiedTaskResult) -> str:
        if result.success and result.output is not None:
            expression = result.output.get("expression")
            value = result.output.get("value")
            return f"我核对过了\uff1a{expression} = {value}"
        if "plugin_timeout" in result.errors:
            return "计算器超时了\uff0c这次没算完"
        if "plugin_crashed" in result.errors:
            return "计算器中途停了\uff0c这次没算完"
        return "这次没有得到能可靠核对的计算结果"

    def render_task_run(self, run: TaskRun) -> str:
        if run.status is TaskRunStatus.WAITING_CONFIRMATION:
            pending = next(
                (step for step in run.plan.steps if step.step_id == run.pending_step_id),
                None,
            )
            if pending is not None and pending.action.handler == "workspace_write":
                path = pending.action.capability_request.arguments.get("path", "目标文件")
                return f"文件 {path} 已准备好, 确认任务 {run.task.task_id} 后写入"
            if pending is not None and pending.action.handler in {
                "daily_plan_write",
                "daily_plan_update",
            }:
                return f"工作计划已准备好, 确认任务 {run.task.task_id} 后保存"
            return f"内容已经核对好了\uff0c保存报告还需要所有者确认\uff0c任务是 {run.task.task_id}"
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
        workspace_writes = [output for output in outputs if output.get("kind") == "workspace_write"]
        plan_writes = [output for output in outputs if output.get("kind") == "daily_plan_write"]
        plan_updates = [output for output in outputs if output.get("kind") == "daily_plan_update"]
        if run.status is TaskRunStatus.COMPLETED and workspace_writes:
            return f"文件已经写入 {workspace_writes[-1].get('path')}"
        if run.status is TaskRunStatus.COMPLETED and plan_writes:
            plan = plan_writes[-1]
            return f"{plan.get('plan_date')} 的工作计划已经保存, 共 {len(plan.get('items', []))} 项"
        if run.status is TaskRunStatus.COMPLETED and plan_updates:
            update = plan_updates[-1]
            return f"计划项 {update.get('item_title')} 已更新为 {update.get('status')}"
        if run.status is TaskRunStatus.COMPLETED and outputs:
            output = outputs[-1]
            if output.get("kind") == "workspace_file":
                return f"文件 {output.get('path')} 已读取, 共 {output.get('bytes')} 字节"
            if output.get("kind") == "workspace_listing":
                return f"目录 {output.get('path')} 已列出, 共 {len(output.get('entries', []))} 项"
            if output.get("kind") == "workspace_search":
                return f"工作区搜索完成, 找到 {len(output.get('matches', []))} 处匹配"
            if output.get("kind") == "web_page":
                return f"网页已读取: {output.get('title') or output.get('url')}"
            if output.get("kind") == "web_search":
                return f"网页搜索完成, 找到 {len(output.get('results', []))} 条结果"
            if output.get("kind") == "daily_plan":
                if not output.get("found"):
                    return f"{output.get('plan_date')} 还没有保存工作计划"
                return f"{output.get('plan_date')} 的工作计划已读取"
        if run.status is TaskRunStatus.COMPLETED and len(calculations) == 1 and not report_saved:
            expression, value = calculations[0]
            return f"我核对过了\uff1a{expression} = {value}"
        if run.status is TaskRunStatus.COMPLETED and report_saved:
            return "任务已经核对完成\uff0c确认后的报告也保存好了"
        if run.status is TaskRunStatus.COMPLETED and calculations:
            summary = "; ".join(f"{expression} = {value}" for expression, value in calculations)
            return f"我核对过了\uff1a{summary}"
        errors = {error for result in run.step_results for error in result.errors}
        single_calculator = (
            len(run.plan.steps) == 1 and run.plan.steps[0].action.handler == "calculator"
        )
        if single_calculator:
            if "plugin_timeout" in errors:
                return "计算器超时了\uff0c这次没算完"
            if "plugin_crashed" in errors:
                return "计算器中途停了\uff0c这次没算完"
            return "这次没有得到能可靠核对的计算结果"
        if "plugin_timeout" in errors:
            return "重试过了\uff0c但任务还是超时了"
        if "plugin_crashed" in errors:
            return "重试过了\uff0c但任务工具还是一直中断"
        if "tainted_write_denied" in errors:
            return "这份内容的来源不适合执行写入\uff0c所以我没有保存"
        if "workspace_path_escape_denied" in errors or "workspace_absolute_path_denied" in errors:
            return "目标路径超出了允许的工作区, 所以我没有访问"
        if "workspace_sensitive_path_denied" in errors:
            return "这个文件属于敏感路径, 不能通过聊天读取或写入"
        if any(error.startswith("web_") for error in errors):
            return "网页读取没有通过网络安全检查, 任务已停止"
        return "任务结果没法可靠核对\uff0c我停掉了后面的步骤"

    def render_task_confirmation_denied(self) -> str:
        return "这次写入仍然需要所有者确认"

    def render_task_confirmation_missing(self) -> str:
        return "这里没有正在等待确认的对应任务"

    def render_continuity_block(self) -> str:
        return "我没有足够的记录支持那样说"

    def render_model_failure(self) -> str:
        return "刚才没能连接到语言模型"

    @staticmethod
    def _semantic_units(text: str, *, maximum: int, unit_chars: int = 120) -> list[str]:
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
        normalized = [line[:unit_chars].strip() for line in lines if line.strip()]
        if not normalized:
            normalized = ["..."]
        if maximum == 1:
            return normalized[:1]
        if len(normalized) <= maximum:
            return normalized
        head = normalized[: maximum - 1]
        tail = " ".join(normalized[maximum - 1 :])[:unit_chars].strip()
        return [*head, tail]
