from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from safevault.processes import safevault_command, spawn_safevault


def test_source_child_command_uses_python_module() -> None:
    command = safevault_command(
        ["daemon", "run"],
        executable=r"C:\Python312\python.exe",
        frozen=False,
    )

    assert command == [
        r"C:\Python312\python.exe",
        "-m",
        "safevault",
        "daemon",
        "run",
    ]


def test_frozen_child_command_runs_packaged_executable_directly() -> None:
    command = safevault_command(
        ["daemon", "run"],
        executable=r"C:\Program Files\SafeVault\safevault.exe",
        frozen=True,
    )

    assert command == [
        r"C:\Program Files\SafeVault\safevault.exe",
        "daemon",
        "run",
    ]
    assert "-m" not in command


def test_child_process_logs_do_not_hold_the_movable_vault_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path / "runtime"
    captured: dict[str, object] = {}
    monkeypatch.setenv("SAFEVAULT_RUNTIME_DIR", str(runtime))

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(pid=123)

    monkeypatch.setattr("safevault.processes.subprocess.Popen", fake_popen)

    spawn_safevault(["ui"], log_name="ui", executable="safevault", frozen=True)

    output = captured["stdout"]
    assert output.name == str(runtime / "logs" / "ui.log")
    assert output.closed is True
