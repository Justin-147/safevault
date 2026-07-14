from __future__ import annotations

from pathlib import Path

SAFETY_PHRASES = (
    "不做裸盘恢复",
    "不是恶意代码沙箱",
    "只能恢复已经被 SafeVault 快照捕获",
    "导出备份",
)


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_core_chinese_docs_cover_required_safety_boundaries() -> None:
    root = _root()
    docs = [
        root / "README.zh-CN.md",
        root / "docs" / "USER_GUIDE_ZH.md",
        root / "docs" / "FAQ_ZH.md",
        root / "docs" / "zh" / "GUI_GUIDE.md",
        root / "docs" / "zh" / "RECOVERY_PLAYBOOK.md",
        root / "docs" / "zh" / "CODEX_WORKFLOW.md",
        root / "docs" / "zh" / "TROUBLESHOOTING.md",
        root / "docs" / "zh" / "SAFETY_MODEL.md",
    ]
    combined = "\n".join(doc.read_text(encoding="utf-8") for doc in docs)
    for phrase in SAFETY_PHRASES:
        assert phrase in combined, f"documentation missing {phrase}"


def test_readmes_link_to_the_documentation_center_and_core_guides() -> None:
    root = _root()
    readme = (root / "README.md").read_text(encoding="utf-8")
    chinese_readme = (root / "README.zh-CN.md").read_text(encoding="utf-8")
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")

    assert "README.zh-CN.md" in readme
    assert "docs/README.md" in readme
    for path in (
        "docs/INSTALL_ZH.md",
        "docs/USER_GUIDE_ZH.md",
        "docs/zh/RECOVERY_PLAYBOOK.md",
        "docs/FAQ_ZH.md",
    ):
        assert path in chinese_readme
    for name in ("INSTALL_EN.md", "USER_GUIDE_EN.md", "FAQ_ZH.md"):
        assert name in docs_index


def test_obsolete_duplicate_user_docs_are_removed() -> None:
    root = _root()
    obsolete = [
        root / "docs" / "zh" / "USER_MANUAL.md",
        root / "docs" / "zh" / "FAQ.md",
        root / "docs" / "zh" / "auto-protection.md",
        root / "docs" / "zh" / "daemon-tray.md",
        root / "docs" / "zh" / "one-click-restore.md",
        root / "docs" / "zh" / "automatic-backup.md",
        root / "docs" / "zh" / "onboarding.md",
        root / "docs" / "dev" / "SAFEVAULT_AUTO_PROTECTION_PRODUCTIZATION_CODEX_PLAN.md",
    ]
    assert not [path for path in obsolete if path.exists()]


def test_user_guides_cover_v1_product_topics() -> None:
    root = _root()
    english = (root / "docs" / "USER_GUIDE_EN.md").read_text(encoding="utf-8")
    chinese = (root / "docs" / "USER_GUIDE_ZH.md").read_text(encoding="utf-8")
    for phrase in (
        "Protect Folders",
        "Backup",
        "Pause Or Stop",
        "Known Limits",
        "emergency-mass-change",
    ):
        assert phrase in english
    for phrase in (
        "保护文件夹",
        "备份",
        "暂停或关闭保护",
        "已知限制",
        "emergency-mass-change",
    ):
        assert phrase in chinese


def test_chinese_readme_has_required_command_and_status_terms() -> None:
    text = (_root() / "README.zh-CN.md").read_text(encoding="utf-8")
    for phrase in (
        "safevault init",
        "safevault restore",
        "safevault ui",
        "不是裸盘恢复",
        "1.1.7",
    ):
        assert phrase in text


def test_gui_guide_documents_confirmation_words() -> None:
    text = (_root() / "docs" / "zh" / "GUI_GUIDE.md").read_text(encoding="utf-8")
    for phrase in (
        "RESTORE",
        "ALLOW DELETE",
        "CLEAN SANDBOXES",
        "OVERWRITE EXPORT",
        "SKIP VERIFY",
        "IMPORT",
    ):
        assert phrase in text


def test_bilingual_release_faqs_exist() -> None:
    root = _root()
    english = (root / "docs" / "FAQ_EN.md").read_text(encoding="utf-8")
    chinese = (root / "docs" / "FAQ_ZH.md").read_text(encoding="utf-8")

    assert "How far back" in english
    assert "SafeVault 最久能恢复多久" in chinese
    assert "not raw-disk recovery" in english
    assert "不是裸盘恢复工具" in chinese


def test_safety_model_documents_core_security_terms() -> None:
    text = (_root() / "docs" / "zh" / "SAFETY_MODEL.md").read_text(encoding="utf-8")
    for phrase in ("BLAKE3", "external symlink", "diff", "导入", "不是恶意代码沙箱"):
        assert phrase in text
