"""Color terminal dashboard for the owner-only psyche API."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from collections.abc import Sequence
from datetime import datetime
from ipaddress import ip_address
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx2
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from living_agent.config import load_settings
from living_agent.models.psyche import (
    ActivityRecord,
    PsycheState,
    ThoughtRecord,
    UnresolvedTopic,
)

ColorMode = Literal["auto", "always", "never"]
DEFAULT_URL = "http://127.0.0.1:8000"


class PsycheCliError(RuntimeError):
    """An actionable error safe to display in the terminal."""


class PsycheSnapshot(BaseModel):
    """One consistent-enough read of the four psyche API views."""

    model_config = ConfigDict(extra="forbid")

    state: PsycheState
    thoughts: list[ThoughtRecord]
    topics: list[UnresolvedTopic]
    activities: list[ActivityRecord]
    fetched_at: datetime


class PsycheApiClient:
    """Small authenticated client for the existing owner control plane."""

    def __init__(
        self,
        *,
        base_url: str,
        actor_id: str,
        token: str | None,
        timeout_seconds: float,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        if transport is None:
            _validate_base_url(base_url)
        headers = {"X-Actor-ID": actor_id, "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx2.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> PsycheApiClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.aclose()

    async def snapshot(
        self,
        *,
        limit: int,
        include_resolved: bool,
    ) -> PsycheSnapshot:
        state_data, thoughts_data, topics_data, activities_data = await asyncio.gather(
            self._get("/v1/psyche/state"),
            self._get(
                "/v1/psyche/thoughts",
                params={"limit": limit, "include_resolved": include_resolved},
            ),
            self._get(
                "/v1/psyche/topics",
                params={"include_resolved": include_resolved},
            ),
            self._get("/v1/psyche/activities", params={"limit": limit}),
        )
        try:
            return PsycheSnapshot(
                state=PsycheState.model_validate(state_data),
                thoughts=TypeAdapter(list[ThoughtRecord]).validate_python(thoughts_data),
                topics=TypeAdapter(list[UnresolvedTopic]).validate_python(topics_data),
                activities=TypeAdapter(list[ActivityRecord]).validate_python(activities_data),
                fetched_at=datetime.now().astimezone(),
            )
        except ValidationError as exc:
            raise PsycheCliError("心理状态接口返回了无法识别的数据") from exc

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> object:
        try:
            response = await self._client.get(path, params=params)
        except httpx2.TimeoutException as exc:
            raise PsycheCliError("连接 LivingAgent 超时") from exc
        except httpx2.HTTPError as exc:
            raise PsycheCliError("无法连接 LivingAgent, 请确认后端已经启动") from exc

        if response.status_code >= 400:
            detail = _response_detail(response)
            if response.status_code == 401:
                message = "管理令牌缺失或无效"
            elif response.status_code == 403:
                message = "当前操作者不是配置的所有者"
            elif response.status_code == 404:
                message = "后端不包含心理状态接口"
            else:
                message = f"心理状态接口返回 HTTP {response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            raise PsycheCliError(message)
        try:
            return response.json()
        except ValueError as exc:
            raise PsycheCliError("心理状态接口没有返回 JSON") from exc


class PsycheDashboard:
    """Rich renderable that keeps all user-derived text markup-safe."""

    def __init__(self, snapshot: PsycheSnapshot, *, base_url: str) -> None:
        self._snapshot = snapshot
        self._base_url = base_url

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        del console, options
        snapshot = self._snapshot
        title = Text("LivingAgent 心理活动", style="bold bright_cyan")
        subtitle = Text()
        subtitle.append(snapshot.fetched_at.strftime("%Y-%m-%d %H:%M:%S"), style="dim")
        subtitle.append("  ")
        subtitle.append(self._base_url, style="bright_black")
        yield Panel(
            Group(title, subtitle),
            border_style="bright_cyan",
            padding=(0, 1),
        )
        yield _state_panel(snapshot.state)
        yield _thought_table(snapshot.thoughts)
        yield _topic_table(snapshot.topics)
        yield _activity_table(snapshot.activities)


def _response_detail(response: httpx2.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    detail = body.get("detail")
    if not isinstance(detail, str):
        return None
    return " ".join(detail.split())[:180]


def _state_panel(state: PsycheState) -> Panel:
    grid = Table.grid(expand=True, padding=(0, 1))
    grid.add_column(width=10, style="bold")
    grid.add_column(ratio=1)
    grid.add_column(width=8, justify="right")
    grid.add_row(
        "情绪效价",
        _signed_bar(state.valence),
        Text(f"{state.valence:+.2f}", style=_valence_style(state.valence)),
    )
    grid.add_row(
        "唤醒度",
        _level_bar(state.arousal, "bright_magenta"),
        Text(f"{state.arousal:.0%}", style="bright_magenta"),
    )
    grid.add_row(
        "关注强度",
        _level_bar(state.focus_salience, "bright_blue"),
        Text(f"{state.focus_salience:.0%}", style="bright_blue"),
    )
    focus = Text(state.current_focus or "当前没有显著关注点")
    focus.stylize("white" if state.current_focus else "dim")
    grid.add_row("当前关注", focus, Text(f"v{state.version}", style="dim"))
    return Panel(grid, title="[bold]心理状态[/bold]", border_style="blue")


def _signed_bar(value: float, *, width: int = 24) -> Text:
    bounded = max(-1.0, min(1.0, value))
    half = width // 2
    negative = round(max(0.0, -bounded) * half)
    positive = round(max(0.0, bounded) * half)
    text = Text()
    text.append("━" * (half - negative), style="bright_black")
    text.append("━" * negative, style="bright_red")
    text.append("◆", style="bold white")
    text.append("━" * positive, style="bright_green")
    text.append("━" * (half - positive), style="bright_black")
    return text


def _level_bar(value: float, style: str, *, width: int = 24) -> Text:
    filled = round(max(0.0, min(1.0, value)) * width)
    text = Text("━" * filled, style=style)
    text.append("━" * (width - filled), style="bright_black")
    return text


def _valence_style(value: float) -> str:
    if value > 0.1:
        return "bold bright_green"
    if value < -0.1:
        return "bold bright_red"
    return "bold yellow"


def _thought_table(thoughts: list[ThoughtRecord]) -> Table:
    table = Table(
        title="近期安全想法",
        title_style="bold bright_magenta",
        border_style="magenta",
        expand=True,
        show_lines=False,
    )
    table.add_column("时间", width=8, style="dim", no_wrap=True)
    table.add_column("类型", width=16, no_wrap=True)
    table.add_column("强度", width=7, justify="right")
    table.add_column("可表达", width=7, justify="right")
    table.add_column("摘要", ratio=1, overflow="fold")
    if not thoughts:
        table.add_row("--", "--", "--", "--", Text("暂无想法记录", style="dim"))
        return table
    for thought in thoughts:
        style = _thought_style(thought.kind)
        table.add_row(
            _local_time(thought.created_at),
            Text(thought.kind, style=style),
            Text(f"{thought.intensity:.0%}", style=style),
            Text(f"{thought.speakability:.0%}", style="cyan"),
            Text(thought.summary, style="dim" if thought.resolved else "white"),
        )
    return table


def _thought_style(kind: str) -> str:
    return {
        "reaction": "bright_green",
        "concern": "yellow",
        "association": "cyan",
        "intention": "bright_blue",
        "doubt": "bright_magenta",
        "suppressed_reply": "bright_black",
        "task_observation": "bright_cyan",
        "memory_trigger": "blue",
    }.get(kind, "white")


def _topic_table(topics: list[UnresolvedTopic]) -> Table:
    table = Table(
        title="未解决话题",
        title_style="bold yellow",
        border_style="yellow",
        expand=True,
    )
    table.add_column("状态", width=10, no_wrap=True)
    table.add_column("建立时间", width=16, no_wrap=True, style="dim")
    table.add_column("摘要", ratio=1, overflow="fold")
    if not topics:
        table.add_row("--", "--", Text("暂无未解决话题", style="dim"))
        return table
    for topic in topics:
        style = "bold yellow" if topic.status.value == "open" else "dim green"
        label = "开放" if topic.status.value == "open" else "已解决"
        table.add_row(
            Text(label, style=style),
            _local_datetime(topic.created_at),
            Text(topic.summary),
        )
    return table


def _activity_table(activities: list[ActivityRecord]) -> Table:
    table = Table(
        title="近期活动",
        title_style="bold bright_green",
        border_style="green",
        expand=True,
    )
    table.add_column("状态", width=10, no_wrap=True)
    table.add_column("类型", width=20, no_wrap=True)
    table.add_column("开始时间", width=16, no_wrap=True, style="dim")
    table.add_column("摘要", ratio=1, overflow="fold")
    if not activities:
        table.add_row("--", "--", "--", Text("暂无活动记录", style="dim"))
        return table
    for activity in activities:
        label, style = {
            "running": ("进行中", "bold bright_cyan"),
            "completed": ("已完成", "bold bright_green"),
            "failed": ("失败", "bold bright_red"),
        }[activity.status.value]
        table.add_row(
            Text(label, style=style),
            Text(activity.kind, style="cyan"),
            _local_datetime(activity.started_at),
            Text(activity.summary),
        )
    return table


def _local_time(value: datetime) -> str:
    return value.astimezone().strftime("%H:%M:%S")


def _local_datetime(value: datetime) -> str:
    return value.astimezone().strftime("%m-%d %H:%M")


def build_parser() -> argparse.ArgumentParser:
    default_actor_id, _default_token = _control_plane_defaults()
    parser = argparse.ArgumentParser(
        prog="living-agent-psyche",
        description="彩色查看 LivingAgent 的心理状态、安全想法、话题和活动。",
    )
    parser.add_argument(
        "--url",
        default=os.getenv("LIVING_AGENT_PSYCHE_URL", DEFAULT_URL),
        help=f"LivingAgent 地址 (默认: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--actor-id",
        default=default_actor_id,
        help="所有者 ID (默认读取 LivingAgent 配置)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("LIVING_AGENT_PSYCHE_TOKEN"),
        help="管理 Bearer 令牌; 非默认地址必须显式提供",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="单次接口超时 (默认: 5)",
    )
    parser.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="颜色模式 (默认: auto; 兼容 NO_COLOR)",
    )
    subparsers = parser.add_subparsers(dest="command")
    show = subparsers.add_parser("show", help="显示一次当前心理活动")
    _add_view_arguments(show)
    watch = subparsers.add_parser("watch", help="持续刷新心理活动")
    _add_view_arguments(watch)
    watch.add_argument(
        "--interval",
        type=float,
        default=2.0,
        metavar="SECONDS",
        help="刷新间隔, 0.25 到 60 秒 (默认: 2)",
    )
    return parser


def _control_plane_defaults() -> tuple[str, str | None]:
    try:
        settings = load_settings()
    except Exception:
        return (
            os.getenv("LIVING_AGENT_OWNER_ID", "owner-local"),
            os.getenv("LIVING_AGENT_MANAGEMENT_API_TOKEN"),
        )
    token = settings.management_api_token
    return settings.owner_id, token.get_secret_value() if token is not None else None


def _add_view_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=int,
        default=12,
        metavar="N",
        help="想法和活动的最大条数 (默认: 12)",
    )
    parser.add_argument(
        "--include-resolved",
        action="store_true",
        help="同时显示已经解决的想法和话题",
    )


def _validate_arguments(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    if args.timeout <= 0 or args.timeout > 120:
        parser.error("--timeout 必须大于 0 且不超过 120")
    if args.limit < 1 or args.limit > 500:
        parser.error("--limit 必须在 1 到 500 之间")
    if args.command == "watch" and not 0.25 <= args.interval <= 60:
        parser.error("--interval 必须在 0.25 到 60 之间")


def _make_console(color_mode: ColorMode) -> Console:
    if color_mode == "always":
        return Console(force_terminal=True, no_color=False, color_system="truecolor")
    if color_mode == "never":
        return Console(force_terminal=False, no_color=True)
    return Console()


async def _show(args: argparse.Namespace, console: Console) -> None:
    async with _client_from_args(args) as client:
        snapshot = await client.snapshot(
            limit=args.limit,
            include_resolved=args.include_resolved,
        )
    console.print(PsycheDashboard(snapshot, base_url=args.url))


async def _watch(args: argparse.Namespace, console: Console) -> None:
    loading = Panel(
        Text("正在连接心理状态后端...", style="bold cyan"),
        border_style="cyan",
    )
    async with _client_from_args(args) as client:
        with Live(
            loading,
            console=console,
            refresh_per_second=8,
            screen=True,
        ) as live:
            while True:
                started = time.monotonic()
                try:
                    snapshot = await client.snapshot(
                        limit=args.limit,
                        include_resolved=args.include_resolved,
                    )
                    live.update(PsycheDashboard(snapshot, base_url=args.url), refresh=True)
                except PsycheCliError as exc:
                    live.update(_error_panel(str(exc), retrying=True), refresh=True)
                elapsed = time.monotonic() - started
                await asyncio.sleep(max(0.0, args.interval - elapsed))


def _client_from_args(args: argparse.Namespace) -> PsycheApiClient:
    return PsycheApiClient(
        base_url=args.url,
        actor_id=args.actor_id,
        token=_token_for_url(args.url, args.token),
        timeout_seconds=args.timeout,
    )


def _token_for_url(base_url: str, explicit_token: str | None) -> str | None:
    if explicit_token is not None:
        return explicit_token
    if not _same_origin(base_url, DEFAULT_URL):
        return None
    _actor_id, default_token = _control_plane_defaults()
    return default_token


def _validate_base_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise PsycheCliError("LivingAgent 地址必须是 HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise PsycheCliError("LivingAgent 地址不能包含凭据、查询参数或片段")
    hostname = parsed.hostname.rstrip(".").casefold()
    try:
        loopback = ip_address(hostname).is_loopback
    except ValueError:
        loopback = hostname == "localhost" or hostname.endswith(".localhost")
    if parsed.scheme != "https" and not loopback:
        raise PsycheCliError("远程 LivingAgent 地址必须使用 HTTPS")


def _same_origin(left: str, right: str) -> bool:
    def origin(value: str) -> tuple[str, str, int | None]:
        parsed = urlsplit(value)
        return parsed.scheme.casefold(), (parsed.hostname or "").casefold(), parsed.port

    try:
        return origin(left) == origin(right)
    except ValueError:
        return False


def _error_panel(message: str, *, retrying: bool) -> Panel:
    body = Text(message, style="bold bright_red")
    if retrying:
        body.append("\n将按刷新间隔自动重试, 按 Ctrl+C 退出。", style="dim")
    return Panel(body, title="连接失败", border_style="bright_red")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        args.command = "show"
        args.limit = 12
        args.include_resolved = False
    _validate_arguments(args, parser)
    console = _make_console(args.color)
    try:
        if args.command == "watch":
            asyncio.run(_watch(args, console))
        else:
            asyncio.run(_show(args, console))
    except KeyboardInterrupt:
        console.print("\n[dim]心理活动监视已停止。[/dim]")
        return 0
    except PsycheCliError as exc:
        console.print(_error_panel(str(exc), retrying=False))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
