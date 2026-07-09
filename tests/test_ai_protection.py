from __future__ import annotations

from safevault.ai_protection import detect_ai_tool


def test_detect_ai_tool_matches_common_ai_coding_commands() -> None:
    assert detect_ai_tool(["codex"]) == "codex"
    assert detect_ai_tool([r"C:\Users\you\AppData\Local\Programs\Cursor\cursor.exe"]) == "cursor"
    assert detect_ai_tool(["python", r"C:\tools\aider.cmd"]) == "aider"
    assert detect_ai_tool(["claude"]) == "claude"
    assert detect_ai_tool(["windsurf.ps1"]) == "windsurf"


def test_detect_ai_tool_ignores_regular_commands() -> None:
    assert detect_ai_tool(["python", "-m", "pytest"]) is None
    assert detect_ai_tool(["node", "scripts/build.js"]) is None
