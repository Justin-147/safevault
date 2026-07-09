from __future__ import annotations

from pathlib import Path


def test_productization_guides_and_windows_scripts_are_present() -> None:
    root = Path(__file__).resolve().parents[1]
    required = [
        root / "docs" / "INSTALL_EN.md",
        root / "docs" / "INSTALL_ZH.md",
        root / "docs" / "USER_GUIDE_EN.md",
        root / "docs" / "USER_GUIDE_ZH.md",
        root / "scripts" / "install_windows_user.ps1",
        root / "scripts" / "uninstall_windows_user.ps1",
    ]

    for path in required:
        assert path.is_file(), f"missing productization artifact: {path}"

    install_en = (root / "docs" / "INSTALL_EN.md").read_text(encoding="utf-8")
    install_zh = (root / "docs" / "INSTALL_ZH.md").read_text(encoding="utf-8")
    user_en = (root / "docs" / "USER_GUIDE_EN.md").read_text(encoding="utf-8")
    user_zh = (root / "docs" / "USER_GUIDE_ZH.md").read_text(encoding="utf-8")
    install_script = (root / "scripts" / "install_windows_user.ps1").read_text(
        encoding="utf-8"
    )
    uninstall_script = (root / "scripts" / "uninstall_windows_user.ps1").read_text(
        encoding="utf-8"
    )

    assert "safevault daemon install" in install_en
    assert "safevault daemon install" in install_zh
    assert "before-ai-change" in user_en
    assert "before-ai-change" in user_zh
    assert "safevault daemon install" in install_script
    assert "safevault daemon uninstall" in uninstall_script


def test_release_check_includes_productization_guides() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    release_check = (root / "scripts" / "release_check.sh").read_text(encoding="utf-8")

    for name in (
        "INSTALL_EN.md",
        "INSTALL_ZH.md",
        "USER_GUIDE_EN.md",
        "USER_GUIDE_ZH.md",
    ):
        assert name in pyproject
        assert name in release_check
    assert '"docs/README.md"' in pyproject
    assert "safevault/ui/docs/README.md" in release_check
