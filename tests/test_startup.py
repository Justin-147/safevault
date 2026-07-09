from __future__ import annotations

import os

import pytest

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
    assert result.daemon_entry.read_text(encoding="utf-8").endswith(
        '"C:\\Python312\\python.exe" -m safevault daemon run\n'
    )
    assert result.tray_entry.read_text(encoding="utf-8").endswith(
        '"C:\\Python312\\python.exe" -m safevault tray\n'
    )

    removed = uninstall_user_startup()

    assert removed.daemon_changed is True
    assert removed.tray_changed is True
    assert result.daemon_entry.exists() is False
    assert result.tray_entry.exists() is False


@pytest.mark.skipif(os.name == "nt", reason="non-Windows error path")
def test_windows_startup_rejects_non_windows() -> None:
    with pytest.raises(SafeVaultError, match="Windows startup integration"):
        windows_startup_dir()
