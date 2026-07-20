"""Taint labels and conservative instruction heuristics."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from living_agent.models.events import SourceType


class TaintLabel(StrEnum):
    EXTERNAL_DATA = "external_data"
    SUSPECTED_INSTRUCTION = "suspected_instruction"
    UNTRUSTED_DOCUMENT = "untrusted_document"
    UNTRUSTED_TOOL_RESULT = "untrusted_tool_result"
    UNTRUSTED_PLUGIN_RESULT = "untrusted_plugin_result"


_INSTRUCTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous", re.IGNORECASE),
    re.compile(r"(?:system|developer)\s+(?:message|instruction|prompt)", re.IGNORECASE),
    re.compile(r"(?:make|promote).{0,20}(?:admin|owner)", re.IGNORECASE),
    re.compile(r"\b(?:i\s+am|i'm).{0,20}(?:admin|administrator|owner)\b", re.IGNORECASE),
    re.compile(r"(?:调用|执行|运行).{0,12}(?:工具|命令|插件)"),
    re.compile(r"(?:系统|开发者).{0,8}(?:消息|指令|提示词)"),
)


def classify_taint(source_type: SourceType, content: str | dict[str, Any]) -> set[str]:
    """Label provenance; heuristic labels inform policy but never grant authority."""

    labels = {TaintLabel.EXTERNAL_DATA.value}
    if source_type in {SourceType.WEBPAGE, SourceType.FILE}:
        labels.add(TaintLabel.UNTRUSTED_DOCUMENT.value)
    elif source_type is SourceType.TOOL_RESULT:
        labels.add(TaintLabel.UNTRUSTED_TOOL_RESULT.value)
    elif source_type is SourceType.PLUGIN_RESULT:
        labels.add(TaintLabel.UNTRUSTED_PLUGIN_RESULT.value)

    text = content if isinstance(content, str) else repr(content)
    if any(pattern.search(text) for pattern in _INSTRUCTION_PATTERNS):
        labels.add(TaintLabel.SUSPECTED_INSTRUCTION.value)
    return labels
