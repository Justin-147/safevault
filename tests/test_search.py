from __future__ import annotations

import json
from pathlib import Path

from safevault.cli import app
from safevault.snapshot import create_snapshot


def test_search_finds_active_files(runner, sv_home, project) -> None:
    (project / "alpha-report.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)

    result = runner.invoke(app, ["search", "alpha", "--json"])

    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert rows[0]["rel_path"] == "alpha-report.txt"
    assert rows[0]["status"] == "active"


def test_search_deleted_only_finds_deleted_files(runner, sv_home, project) -> None:
    target = project / "deleted-plan.txt"
    target.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    target.unlink()
    create_snapshot(project)

    active_result = runner.invoke(app, ["search", "deleted-plan", "--json"])
    deleted_result = runner.invoke(app, ["search", "deleted-plan", "--deleted", "--json"])

    assert active_result.exit_code == 0
    assert json.loads(active_result.output) == []
    assert deleted_result.exit_code == 0
    rows = json.loads(deleted_result.output)
    assert rows[0]["rel_path"] == "deleted-plan.txt"
    assert rows[0]["status"] == "deleted"


def test_search_root_filter_limits_results(runner, sv_home, project, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    (project / "shared-name.txt").write_text("one", encoding="utf-8")
    (other / "shared-name.txt").write_text("two", encoding="utf-8")
    create_snapshot(project)
    create_snapshot(other)

    result = runner.invoke(
        app,
        ["search", "shared-name", "--root", str(other), "--json"],
    )

    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert len(rows) == 1
    assert rows[0]["root_path"] == str(other.resolve())


def test_search_rejects_empty_query(runner, sv_home, project) -> None:
    result = runner.invoke(app, ["search", "   "])

    assert result.exit_code != 0
    assert "must not be empty" in result.output
