from __future__ import annotations

import subprocess
import sys
from typing import IO, Any

from safevault.paths import get_runtime_logs_dir


def safevault_command(
    args: list[str],
    *,
    executable: str | None = None,
    frozen: bool | None = None,
) -> list[str]:
    """Build a SafeVault child command for source and packaged installations."""

    program = executable or sys.executable
    packaged = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if packaged:
        return [program, *args]
    return [program, "-m", "safevault", *args]


def spawn_safevault(
    args: list[str],
    *,
    log_name: str | None = None,
    executable: str | None = None,
    frozen: bool | None = None,
) -> subprocess.Popen[bytes]:
    """Start a detached SafeVault process without opening a Windows console."""

    command = safevault_command(args, executable=executable, frozen=frozen)
    output: IO[bytes] | int = subprocess.DEVNULL
    log_file: IO[bytes] | None = None
    if log_name:
        logs_dir = get_runtime_logs_dir()
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"{log_name}.log"
        log_file = log_path.open("ab")
        output = log_file

    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": output,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(command, **kwargs)
    finally:
        if log_file is not None:
            log_file.close()
