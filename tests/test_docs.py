from __future__ import annotations

from pathlib import Path

SAFETY_PHRASES = (
    "不做裸盘恢复",
    "不是恶意代码沙箱",
    "只能恢复已经被 SafeVault 快照捕获",
    "导出备份",
)


def test_chinese_docs_include_required_safety_phrases() -> None:
    root = Path(__file__).resolve().parents[1]
    docs = [
        root / "README.zh-CN.md",
        root / "docs" / "zh" / "USER_MANUAL.md",
        root / "docs" / "zh" / "GUI_GUIDE.md",
        root / "docs" / "zh" / "RECOVERY_PLAYBOOK.md",
        root / "docs" / "zh" / "CODEX_WORKFLOW.md",
        root / "docs" / "zh" / "FAQ.md",
        root / "docs" / "zh" / "TROUBLESHOOTING.md",
        root / "docs" / "zh" / "SAFETY_MODEL.md",
    ]
    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        for phrase in SAFETY_PHRASES:
            assert phrase in text, f"{doc.name} missing {phrase}"


def test_readme_links_chinese_documentation() -> None:
    root = Path(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    chinese_readme = (root / "README.zh-CN.md").read_text(encoding="utf-8")

    assert "README.zh-CN.md" in readme
    assert "docs/zh/GUI_GUIDE.md" in chinese_readme
    assert "docs/zh/RECOVERY_PLAYBOOK.md" in chinese_readme
    assert "docs/zh/auto-protection.md" in chinese_readme


def test_chinese_readme_has_required_command_and_status_terms() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "README.zh-CN.md").read_text(encoding="utf-8")
    for phrase in (
        "safevault init",
        "safevault restore",
        "safevault ui",
        "不是裸盘恢复",
        "0.2.0rc1",
    ):
        assert phrase in text


def test_gui_guide_documents_confirmation_words() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "docs" / "zh" / "GUI_GUIDE.md").read_text(encoding="utf-8")
    for phrase in (
        "RESTORE",
        "ALLOW DELETE",
        "CLEAN SANDBOXES",
        "OVERWRITE EXPORT",
        "SKIP VERIFY",
        "IMPORT",
    ):
        assert phrase in text


def test_safety_model_documents_core_security_terms() -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / "docs" / "zh" / "SAFETY_MODEL.md").read_text(encoding="utf-8")
    for phrase in ("BLAKE3", "external symlink", "diff", "导入", "不是恶意代码沙箱"):
        assert phrase in text
