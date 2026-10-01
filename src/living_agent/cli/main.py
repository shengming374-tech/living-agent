"""Cross-platform runtime and owner CLI / 跨平台运行时及所有者命令行。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import sys
import webbrowser
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx2
import uvicorn
from pydantic import ValidationError

from living_agent import __version__
from living_agent.cli.profile import (
    Credentials,
    ProfileLock,
    default_profile,
    initialize_profile,
    private_json,
)


def validate_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(
            "请输入服务 origin / Provide a service origin, without a path or credentials"
        )
    try:
        loopback = ip_address(parsed.hostname).is_loopback
    except ValueError:
        loopback = parsed.hostname == "localhost"
    if parsed.scheme != "https" and not loopback:
        raise ValueError("远程连接需要 HTTPS / Remote connections require HTTPS")
    _ = parsed.port
    return value.rstrip("/")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="LivingAgent 应用 / Application CLI")
    result.add_argument("--version", action="version", version=__version__)
    result.add_argument("--data-dir", type=Path, default=default_profile())
    result.add_argument("--url", help="远程服务 HTTPS origin / Remote service origin")
    result.add_argument("--actor", help="远程所有者 ID / Remote owner ID")
    result.add_argument("--json", action="store_true", help="JSON 输出 / JSON output")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="初始化独立数据目录 / Initialize a profile")
    credentials = commands.add_parser("credentials", help="查看本地连接凭据 / Local credentials")
    credentials.add_argument("--reveal", action="store_true", help="显示令牌 / Reveal token")
    serve = commands.add_parser("serve", help="启动运行时 / Start runtime")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--open", action="store_true", help="打开控制台 / Open Studio")
    serve.add_argument("--ready-file", type=Path, help=argparse.SUPPRESS)
    serve.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    commands.add_parser("status", help="服务状态 / Service status")
    commands.add_parser("tools", help="可用工具 / Available tools")
    chat = commands.add_parser("chat", help="人格对话 / Persona chat")
    chat.add_argument("message")
    chat.add_argument("--conversation", default="cli-chat")
    agent = commands.add_parser("agent", help="自主目标 / Persistent goals")
    actions = agent.add_subparsers(dest="action", required=True)
    run = actions.add_parser("run")
    run.add_argument("goal")
    run.add_argument("--conversation", default="cli-agent")
    actions.add_parser("list")
    for name in ("show", "cancel", "confirm", "resume"):
        action = actions.add_parser(name)
        action.add_argument("run_id")
        if name == "resume":
            action.add_argument("--message", required=True)
    group = commands.add_parser("group", help="多智能体群聊 / Multi-agent rooms")
    group_actions = group.add_subparsers(dest="action", required=True)
    group_actions.add_parser("list")
    create = group_actions.add_parser("create")
    create.add_argument("name")
    create.add_argument("--members", type=Path, required=True, help="成员 JSON 文件 / Members JSON")
    for name in ("show", "send", "stop"):
        action = group_actions.add_parser(name)
        action.add_argument("room_id")
        if name == "send":
            action.add_argument("message")
    return result


def output(value: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif isinstance(value, dict) and "messages" in value and "room_id" not in value:
        print("\n".join(value["messages"]) or "本轮保持静默 / No reply")
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))


async def request(args: argparse.Namespace, root: Path) -> Any:
    local_session = root / "session.json"
    if args.url:
        base_url = validate_url(args.url)
        # An explicit origin never inherits local secrets / 显式地址不自动继承本地令牌。
        token = os.environ.get("LIVING_AGENT_CLIENT_TOKEN")
        actor = args.actor or os.environ.get("LIVING_AGENT_CLIENT_ACTOR")
        if not token or not actor:
            raise ValueError("请设置 LIVING_AGENT_CLIENT_TOKEN 和 LIVING_AGENT_CLIENT_ACTOR")
    else:
        credentials = Credentials.model_validate_json(
            (root / "credentials.json").read_text(encoding="utf-8")
        )
        session = json.loads(local_session.read_text(encoding="utf-8"))
        base_url = validate_url(session["url"])
        if not ip_address(urlsplit(base_url).hostname or "").is_loopback:
            raise ValueError("本地会话地址不是回环地址 / Invalid local session origin")
        token, actor = credentials.token, credentials.actor_id
    method, path, body = "GET", "/health", None
    if args.command == "tools":
        path = "/v1/agent/tools"
    elif args.command == "chat":
        method, path = "POST", "/v1/chat"
        body = {
            "content": args.message,
            "source_type": "direct_message",
            "source_identity": actor,
            "conversation_id": args.conversation,
            "authenticated": True,
        }
    elif args.command == "agent":
        path = "/v1/agent/runs"
        if args.action == "run":
            method, body = "POST", {"goal": args.goal, "conversation_id": args.conversation}
        elif args.action != "list":
            path += "/" + quote(args.run_id, safe="")
            if args.action != "show":
                method, path = "POST", path + "/" + args.action
                body = {"message": args.message} if args.action == "resume" else None
    elif args.command == "group":
        path = "/v1/groups"
        if args.action == "create":
            method = "POST"
            body = {"name": args.name, "members": json.loads(args.members.read_text("utf-8"))}
        elif args.action != "list":
            path += "/" + quote(args.room_id, safe="")
            if args.action == "send":
                method, path, body = "POST", path + "/messages", {"content": args.message}
            elif args.action == "stop":
                method, path = "POST", path + "/stop"
    async with httpx2.AsyncClient(
        base_url=base_url,
        trust_env=False,
        follow_redirects=False,
        timeout=180,
        headers={"Authorization": f"Bearer {token}", "X-Actor-ID": actor},
    ) as client:
        response = await client.request(method, path, json=body)
        if response.is_redirect:
            raise ValueError("服务重定向被拒绝 / Service redirects are not followed")
        response.raise_for_status()
        return response.json()


async def run_server(args: argparse.Namespace, root: Path, credentials: Credentials) -> None:
    from living_agent.app import create_app
    from living_agent.config import Settings

    try:
        loopback = ip_address(args.host).is_loopback
    except ValueError as exc:
        raise ValueError("--host 必须是 IP 地址 / --host must be an IP address") from exc
    if not 0 <= args.port <= 65535:
        raise ValueError("端口必须在 0-65535 范围 / Invalid port")
    # Public binding needs production controls, which fail closed without an OS sandbox.
    # 对外监听必须启用生产控制; Windows 缺少插件沙箱时拒绝对外启动。
    overrides: dict[str, Any] = {} if loopback else {"environment": "production"}
    settings = Settings(
        _env_file=root / ".env",
        runtime_root=root,
        database_url=f"sqlite+aiosqlite:///{(root / 'living-agent.sqlite3').as_posix()}",
        owner_id=credentials.actor_id,
        management_api_token=credentials.token,
        work_workspace_root=root / "workspace",
        **overrides,
    )
    app = create_app(settings)
    sock = socket.socket(socket.AF_INET6 if ":" in args.host else socket.AF_INET)
    try:
        sock.bind((args.host, args.port))
        sock.listen(128)
        port = sock.getsockname()[1]
        origin_host = args.host if loopback else "127.0.0.1"
        url = f"http://{'[' + origin_host + ']' if ':' in origin_host else origin_host}:{port}"
        config = uvicorn.Config(app, log_level=settings.log_level.lower(), loop="asyncio")
        started = asyncio.Event()

        class ReadyServer(uvicorn.Server):
            @contextmanager
            def capture_signals(self) -> Iterator[None]:
                # Uvicorn's signal re-raise would terminate before metadata cleanup.
                # 保证优雅停止后能清理连接元数据。
                previous = {
                    sig: signal.signal(sig, self.handle_exit)
                    for sig in (signal.SIGINT, signal.SIGTERM)
                }
                try:
                    yield
                finally:
                    for sig, handler in previous.items():
                        signal.signal(sig, handler)

            async def startup(self, sockets: list[socket.socket] | None = None) -> None:
                await super().startup(sockets=sockets)
                started.set()

        server = ReadyServer(config)

        async def ready() -> None:
            await started.wait()
            if not server.started:
                return
            metadata = {"url": url, "actor_id": credentials.actor_id, "pid": os.getpid()}
            private_json(root / "session.json", metadata)
            if args.ready_file:
                private_json(args.ready_file, {**metadata, "token": credentials.token})
            print(f"LivingAgent {__version__} · {url}/studio", flush=True)
            if args.open:
                webbrowser.open(url + "/studio")
            if args.parent_pid:
                while not server.should_exit:
                    await asyncio.sleep(1)
                    if os.getppid() != args.parent_pid:
                        server.should_exit = True

        readiness = asyncio.create_task(ready())
        try:
            await server.serve(sockets=[sock])
        finally:
            readiness.cancel()
            await asyncio.gather(readiness, return_exceptions=True)
            if args.ready_file:
                args.ready_file.unlink(missing_ok=True)
            path = root / "session.json"
            if path.exists() and json.loads(path.read_text("utf-8")).get("pid") == os.getpid():
                path.unlink()
    finally:
        sock.close()


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    root = args.data_dir.expanduser().resolve()
    try:
        if args.command in {"init", "serve"}:
            with ProfileLock(root):
                credentials = initialize_profile(root)
                if args.command == "init":
                    output(
                        {"data_dir": str(root), "workspace": str(root / "workspace")},
                        as_json=args.json,
                    )
                else:
                    # Never load a checkout's .env or mutable data / 不读取仓库的私有环境与数据。
                    os.chdir(root)
                    os.environ["LIVING_AGENT_RUNTIME_ROOT"] = str(root)
                    asyncio.run(run_server(args, root, credentials))
        elif args.command == "credentials":
            credentials = Credentials.model_validate_json(
                (root / "credentials.json").read_text("utf-8")
            )
            output(
                {
                    "actor_id": credentials.actor_id,
                    "token": credentials.token if args.reveal else "•••• (--reveal)",
                },
                as_json=args.json,
            )
        else:
            output(asyncio.run(request(args, root)), as_json=args.json)
        return 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, ValidationError, httpx2.HTTPError) as exc:
        # Provider/settings errors can embed input secrets / 避免打印含秘密的验证器输入。
        message = (
            str(exc)
            if not isinstance(exc, ValidationError)
            else "配置或凭据无效 / Invalid settings"
        )
        print(f"LivingAgent: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
