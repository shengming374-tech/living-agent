"""工具声明的唯一来源。 / Shared tool schemas, scopes and confirmation requirements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from living_agent.execution.contracts import (
    CALCULATOR_CAPABILITY,
    CALCULATOR_SCOPE,
    CalculatorArguments,
)
from living_agent.execution.shell_contracts import (
    SHELL_EXECUTE_CAPABILITY,
    ShellExecuteArguments,
    shell_scope,
)
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
    daily_plan_scope,
    web_search_scope,
    workspace_scope,
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    capability: str
    operation: str
    arguments: type[BaseModel]
    requires_confirmation: bool = False

    def scope(self, arguments: BaseModel) -> str:
        if isinstance(arguments, CalculatorArguments):
            return CALCULATOR_SCOPE
        if isinstance(arguments, ShellExecuteArguments):
            return shell_scope(arguments)
        if isinstance(arguments, WebFetchArguments):
            return f"url:{arguments.url}"
        if isinstance(arguments, WebSearchArguments):
            return web_search_scope(arguments.query)
        if isinstance(
            arguments, (DailyPlanReadArguments, DailyPlanWriteArguments, DailyPlanUpdateArguments)
        ):
            return daily_plan_scope(arguments.plan_date)
        if isinstance(
            arguments,
            (
                WorkspaceReadArguments,
                WorkspaceListArguments,
                WorkspaceSearchArguments,
                WorkspaceWriteArguments,
            ),
        ):
            return workspace_scope(arguments.path)
        raise ValueError("unsupported tool arguments")

    def scope_matches(self, arguments: BaseModel, scope: str) -> bool:
        return self.scope(arguments) == scope

    def declaration(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.arguments.model_json_schema(),
            "requires_confirmation": self.requires_confirmation,
        }


TOOL_CATALOG = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "calculator",
            "计算算术表达式 / Evaluate arithmetic",
            CALCULATOR_CAPABILITY,
            "execute",
            CalculatorArguments,
        ),
        ToolSpec(
            "workspace_list",
            "列出工作区文件 / List workspace",
            WORKSPACE_LIST_CAPABILITY,
            "list",
            WorkspaceListArguments,
        ),
        ToolSpec(
            "workspace_read",
            "读取工作区文本 / Read workspace text",
            WORKSPACE_READ_CAPABILITY,
            "read",
            WorkspaceReadArguments,
        ),
        ToolSpec(
            "workspace_search",
            "搜索工作区文本 / Search workspace",
            WORKSPACE_SEARCH_CAPABILITY,
            "search",
            WorkspaceSearchArguments,
        ),
        ToolSpec(
            "workspace_write",
            "写入文件 / Write file",
            WORKSPACE_WRITE_CAPABILITY,
            "write",
            WorkspaceWriteArguments,
            True,
        ),
        ToolSpec(
            "web_fetch",
            "读取公开网页 / Read public page",
            WEB_FETCH_CAPABILITY,
            "read",
            WebFetchArguments,
        ),
        ToolSpec(
            "web_search",
            "搜索网页 / Search web",
            WEB_SEARCH_CAPABILITY,
            "search",
            WebSearchArguments,
        ),
        ToolSpec(
            "daily_plan_read",
            "读取每日计划 / Read daily plan",
            DAILY_PLAN_READ_CAPABILITY,
            "read",
            DailyPlanReadArguments,
        ),
        ToolSpec(
            "daily_plan_write",
            "保存每日计划 / Save daily plan",
            DAILY_PLAN_WRITE_CAPABILITY,
            "write",
            DailyPlanWriteArguments,
            True,
        ),
        ToolSpec(
            "daily_plan_update",
            "更新计划条目 / Update plan item",
            DAILY_PLAN_UPDATE_CAPABILITY,
            "update",
            DailyPlanUpdateArguments,
            True,
        ),
        ToolSpec(
            "shell_execute",
            "执行白名单 argv / Execute allowlisted argv",
            SHELL_EXECUTE_CAPABILITY,
            "execute",
            ShellExecuteArguments,
            True,
        ),
    )
}
