"""Clean installed-bundle acceptance / 从便携安装包执行空目录验收。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    bundle = args.bundle.resolve()
    runtime = bundle / ("Contents/Resources/runtime" if bundle.suffix == ".app" else "runtime")
    python = runtime / ("python.exe" if sys.platform == "win32" else "bin/python3")
    with tempfile.TemporaryDirectory(prefix="living-agent-acceptance-") as temporary:
        root = Path(temporary) / "应用数据 with spaces"
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("LIVING_AGENT_", "PYTHON"))
        }
        command = [str(python), "-I", "-B", "-m", "living_agent", "--data-dir", str(root)]
        with (Path(temporary) / "server.log").open("w") as log:

            def start() -> subprocess.Popen[Any]:
                return subprocess.Popen(  # noqa: S603 - fixed packaged interpreter and entry point.
                    [*command, "serve", "--port", "0"],
                    env=env,
                    cwd=temporary,
                    stdout=log,
                    stderr=log,
                )

            def stop(process: subprocess.Popen[Any]) -> None:
                process.terminate()
                process.wait(timeout=30)
                if sys.platform != "win32":
                    assert not (root / "session.json").exists(), "stale session metadata"

            def wait_ready(process: subprocess.Popen[Any]) -> dict[str, Any]:
                for _ in range(600):
                    if (root / "session.json").exists():
                        return json.loads((root / "session.json").read_text("utf-8"))
                    if process.poll() is not None:
                        raise RuntimeError((Path(temporary) / "server.log").read_text("utf-8"))
                    time.sleep(0.1)
                raise RuntimeError("bundle startup timed out")

            process = start()
            try:
                session = wait_ready(process)
                credentials = json.loads((root / "credentials.json").read_text("utf-8"))

                def api(path: str, body: dict[str, Any] | None = None) -> Any:
                    request = urllib.request.Request(  # noqa: S310 - private loopback server metadata.
                        session["url"] + path,
                        data=json.dumps(body).encode() if body is not None else None,
                        headers={
                            "X-Actor-ID": credentials["actor_id"],
                            "Authorization": "Bearer " + credentials["token"],
                            "Content-Type": "application/json",
                        },
                    )
                    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 - loopback fixture.
                        return json.load(response)

                assert api("/health")["status"] == "ok"
                assert len(api("/v1/agent/tools")) == 11
                room = api(
                    "/v1/groups",
                    {
                        "name": "验收群聊",
                        "members": [
                            {"name": "探索者", "persona": "提出想法"},
                            {"name": "审阅者", "persona": "检查证据"},
                        ],
                    },
                )
                room_path = "/v1/groups/" + room["room_id"]
                api(room_path + "/messages", {"content": "讨论计划"})
                for _ in range(100):
                    room = api(room_path)
                    if room["status"] != "responding":
                        break
                    time.sleep(0.1)
                assert room["status"] == "idle" and len(room["messages"]) == 3
                if sys.platform in {"darwin", "win32"}:
                    calculated = api(
                        "/v1/chat",
                        {
                            "content": "计算 7*8",
                            "source_type": "direct_message",
                            "source_identity": credentials["actor_id"],
                            "authenticated": True,
                            "conversation_id": "bundle-calculator",
                        },
                    )
                    assert any("56" in text for text in calculated["messages"]), calculated[
                        "messages"
                    ]
                stop(process)
                # Windows hard terminate leaves stale metadata; startup replaces it after locking.
                # Windows 强制结束会保留旧元数据, 这里清理测试记录后验证重启。
                (root / "session.json").unlink(missing_ok=True)
                process = start()
                session = wait_ready(process)
                assert len(api(room_path)["messages"]) == 3
                print(
                    json.dumps(
                        {
                            "bundle": str(bundle),
                            "health": "ok",
                            "tools": 11,
                            "group_replies": 2,
                            "history_after_restart": True,
                            "calculator": 56,
                            "macos_sandbox_calculator": sys.platform == "darwin",
                        },
                        ensure_ascii=False,
                    )
                )
            finally:
                if process.poll() is None:
                    stop(process)
    if sys.platform == "darwin":
        subprocess.run(  # noqa: S603 - fixed system verifier and the supplied app bundle.
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(bundle)],
            check=True,
        )


if __name__ == "__main__":
    main()
