from __future__ import annotations

from pathlib import Path

from safevault.cli import app


def test_release_acceptance_cli_surface(runner, sv_home) -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in (
        "protect",
        "daemon",
        "backup",
        "ui",
        "retention-plan",
        "verify",
        "doctor",
    ):
        assert command in result.output


def test_release_acceptance_assets_cover_productization_pillars() -> None:
    root = Path(__file__).resolve().parents[1]
    acceptance = (
        root / ".github" / "release" / "v1-productization-acceptance.md"
    ).read_text(encoding="utf-8")
    setup = (root / "packaging" / "windows" / "SafeVaultSetup.iss").read_text(
        encoding="utf-8"
    )
    user_guide = (root / "docs" / "USER_GUIDE_EN.md").read_text(encoding="utf-8")
    release_notes = (root / "docs" / "releases" / "v1.0.3.md").read_text(
        encoding="utf-8"
    )

    for phrase in (
        "SafeVaultSetup.exe",
        "Recovery Home",
        "before/after AI restore points",
        "emergency-mass-change",
        "Dry-run cleanup",
    ):
        assert phrase in acceptance
    assert "Start SafeVault automatically with Windows" in setup
    assert "Protect Folders" in user_guide
    assert "SafeVault v1.0.3" in release_notes
    assert "Upgrade Notes" in release_notes
