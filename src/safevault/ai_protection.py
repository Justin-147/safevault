from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

AI_TOOL_NAMES = {"codex", "cursor"}


def detect_ai_tool(command: Sequence[str]) -> str | None:
    """Return a known AI tool name when a command appears to launch one."""

    for token in command:
        name = _normalized_command_name(token)
        if name in AI_TOOL_NAMES:
            return name
    return None


def is_ai_snapshot_reason(reason: str) -> bool:
    return reason in {
        "before-ai-change",
        "after-ai-change",
        "after-large-change",
    }


def _normalized_command_name(token: str) -> str:
    cleaned = token.strip().strip("\"'")
    if not cleaned:
        return ""
    name = Path(cleaned).name.lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1", ".py"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name
