from __future__ import annotations

from safevault.cli import app
from safevault.tray import tray_available


def test_tray_check_is_safe_when_optional_dependencies_are_missing(runner, sv_home) -> None:
    result = runner.invoke(app, ["tray", "--check"])

    if tray_available():
        assert result.exit_code == 0
        assert "tray dependencies available" in result.output
    else:
        assert result.exit_code != 0
        assert "Install tray dependencies" in result.output
