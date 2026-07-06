from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from safevault.cli import app


def test_cli_imports() -> None:
    assert app is not None


def test_python_module_help_works(sv_home) -> None:
    env = os.environ.copy()
    env["SAFEVAULT_HOME"] = str(sv_home)
    root = Path(__file__).resolve().parents[1]
    pythonpath = [str(root / "src")]
    deps = root / ".py312-deps"
    try:
        next((deps / "typer").iterdir())
    except (OSError, StopIteration):
        pass
    else:
        pythonpath.insert(0, str(deps))
    if env.get("PYTHONPATH"):
        pythonpath.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    result = subprocess.run(
        [sys.executable, "-m", "safevault", "--help"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
    )
    assert result.returncode == 0
    assert "Commands" in result.stdout


def test_doctor_creates_required_directories(runner, sv_home) -> None:
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    for name in ("objects", "logs", "sandboxes", "tmp"):
        assert (sv_home / name).is_dir()
    assert (sv_home / "vault.db").is_file()


def test_expected_user_errors_do_not_show_tracebacks(runner, sv_home, tmp_path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path / "missing")])
    assert result.exit_code != 0
    assert "Error:" in result.output
    assert "Traceback" not in result.output
