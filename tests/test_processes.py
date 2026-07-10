from __future__ import annotations

from safevault.processes import safevault_command


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
