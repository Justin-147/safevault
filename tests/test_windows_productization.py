from __future__ import annotations

from pathlib import Path


def test_windows_installer_assets_define_safevault_setup() -> None:
    root = Path(__file__).resolve().parents[1]
    setup = (root / "packaging" / "windows" / "SafeVaultSetup.iss").read_text(
        encoding="utf-8"
    )
    builder = (root / "scripts" / "build_windows_installer.ps1").read_text(
        encoding="utf-8"
    )
    hidden_launcher = (root / "packaging" / "windows" / "safevault-hidden.vbs").read_text(
        encoding="utf-8"
    )

    assert "OutputBaseFilename=SafeVaultSetup" in setup
    assert "daemon run" in setup
    assert "tray" in setup
    assert "ui --open" in setup
    assert 'MyAppVersion "1.0.1"' in setup
    assert "Start SafeVault background protection" in setup
    assert 'Name: "tray"' in setup and "Flags: checkedonce" in setup
    assert "--collect-all pystray" in builder
    assert "--collect-all PIL" in builder
    assert "PyInstaller failed with exit code" in builder
    assert "SafeVaultSetup.exe" in builder
    assert 'Filename: "{sys}\\wscript.exe"' in setup
    assert "safevault-hidden.vbs" in setup
    assert 'shell.Run command, 0, False' in hidden_launcher
    assert 'Filename: "{app}\\{#MyAppExeName}"' not in setup
