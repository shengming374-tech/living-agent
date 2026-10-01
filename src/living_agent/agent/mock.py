"""无需密钥的可重复演示。 / Deterministic demo, not a language-model substitute."""

import json
from typing import Any

from living_agent.cognition.context_compiler import CompiledContext, ContextKind


def mock_agent_decision(context: CompiledContext) -> str | None:
    task: dict[str, Any] = next(
        (
            json.loads(section.content)
            for section in context.sections
            if section.kind is ContextKind.CURRENT_TASK
        ),
        {},
    )
    if task.get("agent_protocol") != 1:
        return None
    goal = str(task.get("goal", ""))
    observations = [
        json.loads(section.content)
        for section in context.sections
        if section.kind is ContextKind.UNTRUSTED_TOOL_RESULT
    ]
    if not any(token in goal.casefold() for token in ("工作区", "workspace", "readme")):
        return json.dumps(
            {
                "action": "ask",
                "summary": "当前为 Mock 演示模式, 可尝试'检查工作区并读取 README'; "
                "开放目标需要配置 openai_compatible 模型",
            },
            ensure_ascii=False,
        )
    successful = [item for item in observations if item.get("status") == "completed"]
    notes = task.get("input_notes", [])
    requested_path = str(notes[-1]).strip().strip("`\"'") if notes else None
    latest = observations[-1] if observations else {}
    if requested_path and (
        latest.get("tool") != "workspace_read"
        or latest.get("arguments", {}).get("path") != requested_path
    ):
        decision = {
            "action": "tool",
            "summary": "按补充的路径读取工作区文件",
            "tool": "workspace_read",
            "arguments": {"path": requested_path},
        }
    elif latest.get("status") == "failed":
        decision = {"action": "ask", "summary": "本次读取未成功, 请提供工作区内的有效文件路径"}
    elif not observations:
        decision = {
            "action": "tool",
            "summary": "先查看工作区中的实际文件",
            "tool": "workspace_list",
            "arguments": {"path": "."},
        }
    elif successful and successful[-1].get("tool") == "workspace_list":
        entries = (successful[-1].get("output") or {}).get("entries", [])
        readme = next(
            (
                item["path"]
                for item in entries
                if str(item.get("path", "")).lower().endswith("readme.md")
            ),
            None,
        )
        if readme:
            decision = {
                "action": "tool",
                "summary": "根据目录结果读取项目说明",
                "tool": "workspace_read",
                "arguments": {"path": readme},
            }
        else:
            decision = {"action": "ask", "summary": "工作区中未找到 README.md, 请提供要阅读的路径"}
    elif successful and successful[-1].get("tool") == "workspace_read":
        excerpt = str((successful[-1].get("output") or {}).get("text", ""))[:600]
        decision = {
            "action": "finish",
            "summary": f"已检查工作区并读取项目说明, 内容摘录: {excerpt}",
            "evidence_task_ids": [item["task_id"] for item in successful],
        }
    else:
        decision = {"action": "ask", "summary": "本次读取未成功, 请检查工作区路径与文件权限"}
    return json.dumps(decision, ensure_ascii=False)
