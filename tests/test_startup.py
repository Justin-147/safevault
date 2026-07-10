from __future__ import annotations

import os

import pytest

import safevault.startup as startup
from safevault.errors import SafeVaultError
from safevault.startup import install_user_startup, uninstall_user_startup, windows_startup_dir


@pytest.mark.skipif(os.name != "nt", reason="Windows Startup folder is Windows-only")
def test_windows_startup_install_and_uninstall(monkeypatch, tmp_path) -> None:
    appdata = tmp_path / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))

    result = install_user_startup(
        daemon=True,
        tray=True,
        python_executable=r"C:\Python312\python.exe",
    )

    assert result.daemon_changed is True
    assert result.tray_changed is True
    assert result.daemon_entry is not None
    assert result.tray_entry is not None
    daemon_script = result.daemon_entry.read_text(encoding="utf-8")
    tray_script = result.tray_entry.read_text(encoding="utf-8")
    assert 'shell.Run """C:\\Python312\\python.exe"" -m safevault daemon run"' in daemon_script
    assert 'shell.Run """C:\\Python312\\python.exe"" -m safevault tray"' in tray_script
    assert "Dim shell" in daemon_script
    assert ", 0, False" in daemon_script

    removed = uninstall_user_startup()

    assert removed.daemon_changed is True
    assert removed.tray_changed is True
    assert result.daemon_entry.exists() is False
    assert result.tray_entry.exists() is False


@pytest.mark.skipif(os.name == "nt", reason="non-Windows error path")
def test_windows_startup_rejects_non_windows() -> None:
    with pytest.raises(SafeVaultError, match="Windows startup integration"):
        windows_startup_dir()


def test_frozen_startup_command_runs_packaged_executable_directly() -> None:
    command = startup._startup_command(
        r"C:\Program Files\SafeVault\safevault.exe",
        ["daemon", "run"],
        frozen=True,
    )

    assert command == '"C:\\Program Files\\SafeVault\\safevault.exe" daemon run'
    assert "-m safevault" not in command


@pytest.mark.skipif(os.name != "nt", reason="Windows Startup folder is Windows-only")
def test_installer_shortcut_prevents_duplicate_script_entry(monkeypatch, tmp_path) -> None:
    appdata = tmp_path / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    startup_dir = windows_startup_dir()
    startup_dir.mkdir(parents=True)
    link = startup_dir / startup.DAEMON_STARTUP_LINK_NAME
    link.write_bytes(b"installer shortcut")

    result = install_user_startup(daemon=True, tray=False, frozen=True)

    assert result.daemon_entry == link
    assert result.daemon_changed is False
    assert not (startup_dir / startup.DAEMON_STARTUP_NAME).exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows Startup folder is Windows-only")
def test_uninstall_removes_legacy_command_entries(monkeypatch, tmp_path) -> None:
    appdata = tmp_path / "AppData" / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    startup_dir = windows_startup_dir()
    startup_dir.mkdir(parents=True)
    legacy = startup_dir / startup.LEGACY_DAEMON_STARTUP_NAME
    legacy.write_text("legacy", encoding="utf-8")

    result = uninstall_user_startup(daemon=True, tray=False)

    assert result.daemon_changed is True
    assert legacy.exists() is False
