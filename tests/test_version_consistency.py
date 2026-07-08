from __future__ import annotations

import tomllib
from pathlib import Path

from safevault import __version__


def test_version_strings_are_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    readme_zh = (root / "README.zh-CN.md").read_text(encoding="utf-8")

    assert pyproject["project"]["version"] == __version__ == "0.2.0rc1"
    assert "## 0.2.0rc1" in changelog
    assert "v0.2.0-rc1" in readme
    assert "0.2.0rc1" in readme_zh
