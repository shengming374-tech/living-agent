"""Conservative natural-language routing for bounded host work actions."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal

from living_agent.execution.shell_contracts import (
    SHELL_EXECUTE_CAPABILITY,
    SHELL_EXECUTE_HANDLER,
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
    daily_plan_scope,
    normalize_web_url,
    web_search_scope,
    workspace_scope,
)
from living_agent.models.life import DailyPlanItemInput, PlanItemKind

WorkHandler = Literal[
    "workspace_read",
    "workspace_list",
    "workspace_search",
    "workspace_write",
    "web_fetch",
    "web_search",
    "daily_plan_read",
    "daily_plan_write",
    "daily_plan_update",
    "shell_execute",
]

_URL = re.compile(r"https?://[^\s<>\]\[\"']+", re.IGNORECASE)
_FILE_PATH = re.compile(
    r"(?P<path>(?:[\w.@+~-]+/)*[\w.@+~-]+\."
    r"(?:md|txt|rst|json|ya?ml|toml|ini|cfg|csv|tsv|log|py|js|ts|tsx|jsx|html?|css|sql))",
    re.IGNORECASE,
)
_FILE_WRITE = re.compile(
    r"^\s*(?:请|帮我)?\s*(?:创建|新建|写入|保存|write|create)\s*"
    r"(?:一个\s*)?(?:文件\s*)?[`\"'“”]?"
    r"(?P<path>[^`\"'“”\uff1a:\s]+)[`\"'“”]?\s*"
    r"(?:\uff0c?\s*内容\s*(?:为|是)?\s*|[:\uff1a]\s*)(?P<content>[\s\S]+)$",
    re.IGNORECASE,
)
_SHELL_CWD_PREFIX = re.compile(
    r"^\s*(?:请|帮我)?\s*在\s*[`\"'“”]?(?P<cwd>[^`\"'“”\s]+)"
    r"[`\"'“”]?\s*(?:目录)?(?:中|里)\s*[,\uff0c]?\s*",
    re.IGNORECASE,
)
_SHELL_FENCED = re.compile(
    r"^\s*(?:请|帮我)?\s*(?:运行|执行|跑一下|run|execute)\s*"
    r"(?:(?:shell|终端)\s*)?(?:命令|command)?\s*[`]\s*(?P<command>.+?)\s*[`]\s*$",
    re.IGNORECASE,
)
_SHELL_EXPLICIT = re.compile(
    r"^\s*(?:请|帮我)?\s*(?:运行|执行|run|execute)\s*"
    r"(?:(?:shell|终端)\s*)?(?:命令|command)\s*[:\uff1a]\s*(?P<command>.+?)\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class WorkActionSpec:
    title: str
    handler: WorkHandler
    capability: str
    operation: str
    resource_scope: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParsedWorkRequest:
    goal: str
    actions: tuple[WorkActionSpec, ...]
    requires_synthesis: bool

    @property
    def writes(self) -> bool:
        return any(
            action.operation in {"write", "create", "update"}
            or action.handler == SHELL_EXECUTE_HANDLER
            for action in self.actions
        )


def parse_work_request(
    text: str,
    *,
    today: date | None = None,
    _allow_composite: bool = True,
) -> ParsedWorkRequest | None:
    normalized = text.strip()
    if not normalized:
        return None
    resolved_today = today or date.today()
    if _allow_composite:
        without_prefix = re.sub(
            r"^\s*(?:任务|task)\s*[:\uff1a]\s*",
            "",
            normalized,
            count=1,
            flags=re.IGNORECASE,
        )
        segments = [
            segment.strip()
            for segment in re.split(r"[\uff1b;\n]+", without_prefix)
            if segment.strip()
        ]
        parsed_segments = [
            parse_work_request(
                segment,
                today=resolved_today,
                _allow_composite=False,
            )
            for segment in segments
        ]
        if 1 < len(parsed_segments) <= 8 and all(item is not None for item in parsed_segments):
            completed = [item for item in parsed_segments if item is not None]
            return ParsedWorkRequest(
                goal="; ".join(item.goal for item in completed)[:2000],
                actions=tuple(action for item in completed for action in item.actions),
                requires_synthesis=any(item.requires_synthesis for item in completed),
            )
    target_date = _requested_date(normalized, resolved_today)

    shell = _parse_shell(normalized)
    if shell is not None:
        return shell

    plan = _parse_daily_plan(normalized, target_date)
    if plan is not None:
        return plan

    write_match = _FILE_WRITE.fullmatch(normalized)
    if write_match is not None and "任务报告" not in normalized:
        path = _clean_path(write_match.group("path"))
        content = write_match.group("content").strip()
        if path and content:
            creating = bool(re.search(r"(?:创建|新建|create)", normalized, re.IGNORECASE))
            return ParsedWorkRequest(
                goal=f"Write the explicitly supplied content to {path}",
                actions=(
                    WorkActionSpec(
                        title=f"Write workspace file {path}",
                        handler="workspace_write",
                        capability=WORKSPACE_WRITE_CAPABILITY,
                        operation="write",
                        resource_scope=workspace_scope(path),
                        arguments={
                            "path": path,
                            "content": content[:200_000],
                            "overwrite": not creating,
                        },
                    ),
                ),
                requires_synthesis=False,
            )

    url_match = _URL.search(normalized)
    if url_match is not None and re.search(
        r"(?:读取|打开|查看|总结|分析|访问|read|open|summari[sz]e|analy[sz]e)",
        normalized,
        re.IGNORECASE,
    ):
        url = url_match.group(0).rstrip("\u3002.,\uff0c\uff1b;!?\uff01\uff1f)")
        return ParsedWorkRequest(
            goal=f"Read and answer from the requested web page {url}",
            actions=(
                WorkActionSpec(
                    title="Read public web page",
                    handler="web_fetch",
                    capability=WEB_FETCH_CAPABILITY,
                    operation="read",
                    resource_scope=f"url:{normalize_web_url(url)}",
                    arguments={"url": url, "max_chars": 20_000},
                ),
            ),
            requires_synthesis=True,
        )

    workspace_search = _parse_workspace_search(normalized)
    if workspace_search is not None:
        return workspace_search

    web_search = _parse_web_search(normalized)
    if web_search is not None:
        return web_search

    listing = _parse_workspace_listing(normalized)
    if listing is not None:
        return listing

    path_match = _FILE_PATH.search(normalized)
    wants_file = re.search(
        r"(?:读取|查看|打开|总结|分析|概括|read|open|summari[sz]e|analy[sz]e)",
        normalized,
        re.IGNORECASE,
    )
    if path_match is not None and wants_file is not None:
        path = _clean_path(path_match.group("path"))
        return _workspace_read_request(path, goal=f"Read and answer from {path}")

    project_summary = r"(?:写一份|生成|整理|做)(?:这个|本)?项目(?:的)?总结"
    project_summary += r"|总结(?:一下)?(?:这个|本)?项目"
    if re.search(project_summary, normalized):
        return _workspace_read_request(
            "README.md",
            goal="Read the project README and produce the requested project summary",
        )
    return None


def _parse_shell(text: str) -> ParsedWorkRequest | None:
    cwd = "."
    command_text = text
    cwd_match = _SHELL_CWD_PREFIX.match(command_text)
    if cwd_match is not None:
        cwd = _clean_path(cwd_match.group("cwd"))
        command_text = command_text[cwd_match.end() :]

    normalized = " ".join(command_text.casefold().split())
    aliases: dict[str, list[str]] = {
        "运行测试": ["uv", "run", "pytest"],
        "执行测试": ["uv", "run", "pytest"],
        "跑一下测试": ["uv", "run", "pytest"],
        "跑测试": ["uv", "run", "pytest"],
        "run tests": ["uv", "run", "pytest"],
        "运行代码检查": ["uv", "run", "ruff", "check", "."],
        "执行代码检查": ["uv", "run", "ruff", "check", "."],
        "检查代码规范": ["uv", "run", "ruff", "check", "."],
        "run lint": ["uv", "run", "ruff", "check", "."],
        "运行类型检查": ["uv", "run", "mypy"],
        "执行类型检查": ["uv", "run", "mypy"],
        "run type check": ["uv", "run", "mypy"],
        "查看 git 状态": ["git", "status", "--short"],
        "查看git状态": ["git", "status", "--short"],
        "git status": ["git", "status", "--short"],
    }
    argv = aliases.get(normalized)
    if argv is None:
        match = _SHELL_FENCED.fullmatch(command_text) or _SHELL_EXPLICIT.fullmatch(
            command_text
        )
        if match is None:
            return None
        try:
            argv = shlex.split(match.group("command"), posix=True)
        except ValueError:
            return None
    try:
        arguments = ShellExecuteArguments(
            argv=argv,
            cwd=cwd,
        )
    except ValueError:
        return None
    display = shlex.join(arguments.argv)
    return ParsedWorkRequest(
        goal=f"Run the confirmed workspace command: {display}",
        actions=(
            WorkActionSpec(
                title=f"Run workspace command {display[:120]}",
                handler="shell_execute",
                capability=SHELL_EXECUTE_CAPABILITY,
                operation="execute",
                resource_scope=shell_scope(arguments),
                arguments=arguments.model_dump(mode="json"),
            ),
        ),
        requires_synthesis=False,
    )


def _parse_daily_plan(text: str, plan_date: date) -> ParsedWorkRequest | None:
    if not re.search(r"(?:工作计划|每日计划|日计划|待办)", text):
        return None
    status_match = re.search(
        r"(?:工作计划|每日计划|日计划|待办)(?:中的|中)?\s*"
        r"[`\"'“”]?(.+?)[`\"'“”]?\s*"
        r"(?:标记为|设为|改为|已经|已)?\s*(完成|进行中|开始|跳过)$",
        text,
    )
    if status_match is not None:
        requested_status = status_match.group(2)
        status = {
            "完成": "completed",
            "进行中": "in_progress",
            "开始": "in_progress",
            "跳过": "skipped",
        }[requested_status]
        item_title = status_match.group(1).strip()
        return ParsedWorkRequest(
            goal=(f"Update daily plan item {item_title} to {status} for {plan_date.isoformat()}"),
            actions=(
                WorkActionSpec(
                    title=f"Update daily plan item {item_title[:80]}",
                    handler="daily_plan_update",
                    capability=DAILY_PLAN_UPDATE_CAPABILITY,
                    operation="update",
                    resource_scope=daily_plan_scope(plan_date),
                    arguments={
                        "plan_date": plan_date.isoformat(),
                        "item_title": item_title,
                        "status": status,
                    },
                ),
            ),
            requires_synthesis=False,
        )
    content_match = re.search(r"[:\uff1a]\s*(.+)$", text, re.DOTALL)
    write_intent = re.search(r"(?:创建|新建|制定|保存|安排|加入|添加)", text)
    if write_intent is not None and content_match is not None:
        titles = _split_plan_items(content_match.group(1))
        if not titles:
            return None
        items = [
            DailyPlanItemInput(
                title=title,
                kind=PlanItemKind.ROUTINE,
                expected_minutes=30,
            ).model_dump(mode="json")
            for title in titles[:50]
        ]
        return ParsedWorkRequest(
            goal=f"Save the requested daily work plan for {plan_date.isoformat()}",
            actions=(
                WorkActionSpec(
                    title=f"Save daily plan for {plan_date.isoformat()}",
                    handler="daily_plan_write",
                    capability=DAILY_PLAN_WRITE_CAPABILITY,
                    operation="write",
                    resource_scope=daily_plan_scope(plan_date),
                    arguments={
                        "plan_date": plan_date.isoformat(),
                        "intention": f"完成 {len(items)} 项明确工作",
                        "items": items,
                        "expected_version": None,
                        "mode": ("append" if re.search(r"(?:加入|添加)", text) else "replace"),
                    },
                ),
            ),
            requires_synthesis=False,
        )
    if re.search(r"(?:查看|看看|读取|显示|有什么|整理|安排|计划)", text):
        return ParsedWorkRequest(
            goal=f"Read the daily work plan for {plan_date.isoformat()}",
            actions=(
                WorkActionSpec(
                    title=f"Read daily plan for {plan_date.isoformat()}",
                    handler="daily_plan_read",
                    capability=DAILY_PLAN_READ_CAPABILITY,
                    operation="read",
                    resource_scope=daily_plan_scope(plan_date),
                    arguments={"plan_date": plan_date.isoformat()},
                ),
            ),
            requires_synthesis=True,
        )
    return None


def _parse_workspace_search(text: str) -> ParsedWorkRequest | None:
    path_match = re.search(r"(?:在|于)\s*[`\"'“”]?([^`\"'“”\s]+)[`\"'“”]?\s*(?:中|里)", text)
    workspace_marker = (
        r"(?:工作区|代码|文件|项目).*(?:搜索|查找)"
        r"|(?:搜索|查找).*(?:代码|文件|工作区)"
    )
    if not re.search(workspace_marker, text) and path_match is None:
        return None
    query_match = re.search(r"(?:搜索|查找)\s*[`\"'“”]?(.+?)[`\"'“”]?(?:\s+(?:在|于).*)?$", text)
    if query_match is None:
        return None
    query = query_match.group(1).strip(" `\"'“”\uff1a:")
    query = re.sub(r"(?:这个)?(?:文本|内容|字符串|代码)$", "", query).strip()
    if not query:
        return None
    path = _clean_path(path_match.group(1)) if path_match is not None else "."
    return ParsedWorkRequest(
        goal=f"Search workspace path {path} for {query}",
        actions=(
            WorkActionSpec(
                title=f"Search workspace for {query[:80]}",
                handler="workspace_search",
                capability=WORKSPACE_SEARCH_CAPABILITY,
                operation="search",
                resource_scope=workspace_scope(path),
                arguments={"path": path, "query": query, "max_matches": 100},
            ),
        ),
        requires_synthesis=True,
    )


def _parse_web_search(text: str) -> ParsedWorkRequest | None:
    explicit = re.search(r"(?:网络|网页|网上|联网)\s*(?:搜索|查找|搜一下)", text)
    news_or_research = re.search(r"(?:搜索|搜一下|查找).*(?:新闻|资讯|资料|网页|网上)", text)
    if explicit is None and news_or_research is None:
        return None
    query = re.sub(
        r"^\s*(?:请|帮我|麻烦)?\s*(?:(?:在)?(?:网络|网页|网上|联网)(?:上)?\s*)?"
        r"(?:搜索|搜一下|查找)\s*",
        "",
        text,
    ).strip(" \uff1a:")
    if not query:
        return None
    return ParsedWorkRequest(
        goal=f"Search the public web for {query}",
        actions=(
            WorkActionSpec(
                title=f"Search the public web for {query[:80]}",
                handler="web_search",
                capability=WEB_SEARCH_CAPABILITY,
                operation="search",
                resource_scope=web_search_scope(query),
                arguments={"query": query, "max_results": 8},
            ),
        ),
        requires_synthesis=True,
    )


def _parse_workspace_listing(text: str) -> ParsedWorkRequest | None:
    if not re.search(r"(?:列出|浏览|查看).*(?:目录|文件夹|工作区.*文件|项目.*文件)", text):
        return None
    path_match = re.search(
        r"(?:目录|文件夹)\s*[`\"'“”]?([^`\"'“”\s]+)[`\"'“”]?",
        text,
    )
    path = _clean_path(path_match.group(1)) if path_match is not None else "."
    recursive = bool(re.search(r"(?:递归|所有|全部)", text))
    return ParsedWorkRequest(
        goal=f"List files in workspace path {path}",
        actions=(
            WorkActionSpec(
                title=f"List workspace directory {path}",
                handler="workspace_list",
                capability=WORKSPACE_LIST_CAPABILITY,
                operation="list",
                resource_scope=workspace_scope(path),
                arguments={"path": path, "recursive": recursive, "max_entries": 200},
            ),
        ),
        requires_synthesis=True,
    )


def _workspace_read_request(path: str, *, goal: str) -> ParsedWorkRequest:
    return ParsedWorkRequest(
        goal=goal,
        actions=(
            WorkActionSpec(
                title=f"Read workspace file {path}",
                handler="workspace_read",
                capability=WORKSPACE_READ_CAPABILITY,
                operation="read",
                resource_scope=workspace_scope(path),
                arguments={"path": path, "max_chars": 20_000},
            ),
        ),
        requires_synthesis=True,
    )


def _requested_date(text: str, today: date) -> date:
    iso_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if iso_match is not None:
        try:
            return date.fromisoformat(iso_match.group(1))
        except ValueError:
            pass
    if "明天" in text:
        return today + timedelta(days=1)
    if "昨天" in text:
        return today - timedelta(days=1)
    return today


def _split_plan_items(content: str) -> list[str]:
    raw_items = re.split(r"[\uff1b;\n]+|(?<=\S)、(?=\S)", content)
    items = []
    for raw in raw_items:
        normalized = re.sub(r"^\s*(?:[-*]|\d+[.、)])\s*", "", raw).strip()
        if normalized and normalized not in items:
            items.append(normalized[:300])
    return items


def _clean_path(value: str) -> str:
    return value.strip().strip("`\"'“”").replace("\\", "/")
