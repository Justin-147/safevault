from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from safevault.errors import SafeVaultError

DAEMON_STARTUP_NAME = "SafeVault Daemon.vbs"
TRAY_STARTUP_NAME = "SafeVault Tray.vbs"
DAEMON_STARTUP_LINK_NAME = "SafeVault Daemon.lnk"
TRAY_STARTUP_LINK_NAME = "SafeVault Tray.lnk"
LEGACY_DAEMON_STARTUP_NAME = "SafeVault Daemon.cmd"
LEGACY_TRAY_STARTUP_NAME = "SafeVault Tray.cmd"


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
    frozen: bool | None = None,
) -> StartupInstallResult:
    startup = windows_startup_dir()
    startup.mkdir(parents=True, exist_ok=True)
    executable = python_executable or sys.executable
    frozen_app = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    daemon_entry = None
    tray_entry = None
    daemon_changed = False
    tray_changed = False
    if daemon:
        daemon_link = startup / DAEMON_STARTUP_LINK_NAME
        daemon_entry = daemon_link if daemon_link.exists() else startup / DAEMON_STARTUP_NAME
        if daemon_entry.suffix.lower() != ".lnk":
            daemon_changed = _write_vbs(
                daemon_entry,
                executable,
                ["daemon", "run"],
                frozen=frozen_app,
            )
    if tray:
        tray_link = startup / TRAY_STARTUP_LINK_NAME
        tray_entry = tray_link if tray_link.exists() else startup / TRAY_STARTUP_NAME
        if tray_entry.suffix.lower() != ".lnk":
            tray_changed = _write_vbs(
                tray_entry,
                executable,
                ["tray"],
                frozen=frozen_app,
            )
    return StartupInstallResult(
        daemon_entry=daemon_entry,
        tray_entry=tray_entry,
        daemon_changed=daemon_changed,
        tray_changed=tray_changed,
    )


def uninstall_user_startup(*, daemon: bool = True, tray: bool = True) -> StartupInstallResult:
    startup = windows_startup_dir()
    daemon_entries = (
        [
            startup / DAEMON_STARTUP_NAME,
            startup / LEGACY_DAEMON_STARTUP_NAME,
            startup / DAEMON_STARTUP_LINK_NAME,
        ]
        if daemon
        else []
    )
    tray_entries = (
        [
            startup / TRAY_STARTUP_NAME,
            startup / LEGACY_TRAY_STARTUP_NAME,
            startup / TRAY_STARTUP_LINK_NAME,
        ]
        if tray
        else []
    )
    daemon_entry = next((entry for entry in daemon_entries if entry.exists()), None)
    tray_entry = next((entry for entry in tray_entries if entry.exists()), None)
    daemon_changed = daemon_entry is not None
    tray_changed = tray_entry is not None
    for entry in [*daemon_entries, *tray_entries]:
        if entry.exists():
            entry.unlink()
    return StartupInstallResult(
        daemon_entry=daemon_entry,
        tray_entry=tray_entry,
        daemon_changed=daemon_changed,
        tray_changed=tray_changed,
    )


def _startup_command(executable: str, args: list[str], *, frozen: bool) -> str:
    prefix = [] if frozen else ["-m", "safevault"]
    return " ".join([f'"{executable}"', *prefix, *args])


def _write_vbs(path: Path, executable: str, args: list[str], *, frozen: bool) -> bool:
    command = _startup_command(executable, args, frozen=frozen).replace('"', '""')
    content = (
        'Option Explicit\r\nDim shell\r\nSet shell = CreateObject("WScript.Shell")\r\n'
        f'shell.Run "{command}", 0, False\r\n'
    )
    encoded = content.encode("utf-8")
    if path.exists() and path.read_bytes() == encoded:
        return False
    path.write_bytes(encoded)
    return True
