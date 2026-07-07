from __future__ import annotations

from safevault.cli import app
from safevault.object_store import object_path
from safevault.snapshot import create_snapshot
from safevault.verify import run_verify


def test_verify_fast_reports_missing_object(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    digest = _first_hash()
    object_path(digest).unlink()
    result = run_verify()
    assert not result.healthy
    assert digest in result.missing_objects


def test_verify_deep_reports_corrupted_object(runner, sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    digest = _first_hash()
    object_path(digest).write_text("corrupt", encoding="utf-8")
    result = runner.invoke(app, ["verify", "--deep"])
    assert result.exit_code == 1
    assert "Corrupted objects" in result.output


def test_verify_reports_invalid_reference(runner, sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    _set_first_content_hash("not-a-hash")
    result = run_verify()
    assert not result.healthy
    assert result.invalid_references == ["not-a-hash"]
    cli_result = runner.invoke(app, ["verify"])
    assert cli_result.exit_code == 1
    assert "Invalid references" in cli_result.output


def test_verify_json_output(runner, sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    result = runner.invoke(app, ["verify", "--json"])
    assert result.exit_code == 0
    data = __import__("json").loads(result.output)
    assert data["healthy"] is True
    assert data["invalid_references"] == []


def test_verify_fast_does_not_rehash_clean_existing_object(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    result = run_verify()
    assert result.healthy
    assert result.checked_objects == 1


def _first_hash() -> str:
    from safevault.db import connect

    conn = connect()
    try:
        return str(conn.execute("SELECT content_hash FROM versions").fetchone()["content_hash"])
    finally:
        conn.close()


def _set_first_content_hash(value: str) -> None:
    from safevault.db import connect

    conn = connect()
    try:
        conn.execute("UPDATE versions SET content_hash = ? WHERE id = 1", (value,))
        conn.commit()
    finally:
        conn.close()
