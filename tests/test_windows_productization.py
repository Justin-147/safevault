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

    assert "OutputBaseFilename=SafeVaultSetup" in setup
    assert "daemon run" in setup
    assert "tray" in setup
    assert "ui --open" in setup
    assert "SafeVaultSetup.exe" in builder
