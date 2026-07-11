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
    release_check = (root / "scripts" / "release_check.sh").read_text(
        encoding="utf-8"
    )
    onboarding_smoke = (root / "scripts" / "onboarding_smoke.py").read_text(
        encoding="utf-8"
    )

    assert pyproject["project"]["version"] == __version__ == "1.0.3"
    assert "## 1.0.3" in changelog
    assert "v1.0.3" in readme
    assert "1.0.3" in readme_zh
    assert 'assert __version__ == "1.0.3"' in release_check
    assert '"safevault/ui/static/safevault.js"' in release_check
    assert "设置完成" in onboarding_smoke
    assert "pre-daemon-start" in onboarding_smoke
    assert "onboarding-initial" not in onboarding_smoke
