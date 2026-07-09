from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from safevault.errors import SafeVaultError

DAEMON_STARTUP_NAME = "SafeVault Daemon.cmd"
TRAY_STARTUP_NAME = "SafeVault Tray.cmd"


@dataclass(frozen=True)
class StartupInstallResult:
    daemon_entry: Path | None
    tray_entry: Path | None
    daemon_changed: bool = False
    tray_changed: bool = False


def windows_startup_dir() -> Path:
    if os.name != "nt":
        raise SafeVaultError("Windows startup integration is only supported on Windows")
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SafeVaultError("APPDATA is not set; cannot locate Windows Startup folder")
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )


def install_user_startup(
    *,
    daemon: bool = True,
    tray: bool = False,
    python_executable: str | None = None,
) -> StartupInstallResult:
    startup = windows_startup_dir()
    startup.mkdir(parents=True, exist_ok=True)
    python = python_executable or sys.executable
    daemon_entry = None
    tray_entry = None
    if daemon:
        daemon_entry = startup / DAEMON_STARTUP_NAME
        _write_cmd(daemon_entry, python, ["-m", "safevault", "daemon", "run"])
    if tray:
        tray_entry = startup / TRAY_STARTUP_NAME
        _write_cmd(tray_entry, python, ["-m", "safevault", "tray"])
    return StartupInstallResult(
        daemon_entry=daemon_entry,
        tray_entry=tray_entry,
        daemon_changed=daemon,
        tray_changed=tray,
    )


def uninstall_user_startup(*, daemon: bool = True, tray: bool = True) -> StartupInstallResult:
    startup = windows_startup_dir()
    daemon_entry = startup / DAEMON_STARTUP_NAME if daemon else None
    tray_entry = startup / TRAY_STARTUP_NAME if tray else None
    daemon_changed = daemon_entry is not None and daemon_entry.exists()
    tray_changed = tray_entry is not None and tray_entry.exists()
    for entry in (daemon_entry, tray_entry):
        if entry is not None and entry.exists():
            entry.unlink()
    return StartupInstallResult(
        daemon_entry=daemon_entry,
        tray_entry=tray_entry,
        daemon_changed=daemon_changed,
        tray_changed=tray_changed,
    )


def _write_cmd(path: Path, python: str, args: list[str]) -> None:
    quoted_args = " ".join(args)
    path.write_text(
        f'@echo off\r\n"{python}" {quoted_args}\r\n',
        encoding="utf-8",
        newline="",
    )
