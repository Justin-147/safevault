from __future__ import annotations

from safevault.cli import app
from safevault.db import connect
from safevault.snapshot import create_snapshot


def test_versions_lists_multiple_versions_newest_first(runner, sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    file_path.write_text("v2", encoding="utf-8")
    create_snapshot(project)
    conn = connect()
    try:
        ids = [str(row["id"]) for row in conn.execute("SELECT id FROM versions ORDER BY id")]
    finally:
        conn.close()
    result = runner.invoke(app, ["versions", str(file_path)])
    assert result.exit_code == 0
    assert result.output.find(ids[-1]) < result.output.find(ids[0])


def test_versions_includes_deleted_marker_and_deleted_finds_it(runner, sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    file_path.unlink()
    create_snapshot(project)
    versions_result = runner.invoke(app, ["versions", str(file_path)])
    deleted_result = runner.invoke(app, ["deleted", "--since", "24h"])
    assert versions_result.exit_code == 0
    assert "yes" in versions_result.output
    assert deleted_result.exit_code == 0
    assert "a.txt" in deleted_result.output


def test_invalid_duration_fails_clearly(runner, sv_home) -> None:
    result = runner.invoke(app, ["deleted", "--since", "soon"])
    assert result.exit_code != 0
    assert "invalid duration" in result.output
    assert "Traceback" not in result.output


def test_file_outside_protected_root_fails_clearly(runner, sv_home, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["versions", str(outside)])
    assert result.exit_code != 0
    assert "protected root" in result.output
