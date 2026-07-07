from __future__ import annotations

import json
import shutil

from safevault.cli import app
from safevault.doctor import run_doctor
from safevault.object_store import object_path, store_bytes
from safevault.snapshot import create_snapshot


def test_doctor_reports_missing_referenced_object(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    digest = _first_content_hash()
    object_path(digest).unlink()
    result = run_doctor()
    assert not result.healthy
    assert digest in result.missing_objects


def test_doctor_reports_orphan_object_warning(sv_home) -> None:
    digest = store_bytes(b"orphan")
    result = run_doctor()
    assert result.healthy
    assert digest in result.orphan_objects


def test_doctor_reports_missing_root(sv_home, project) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    shutil.rmtree(project)
    result = run_doctor()
    assert not result.healthy
    assert str(project.resolve()) in result.missing_roots


def test_doctor_json_cli(runner, sv_home) -> None:
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["healthy"] is True
    assert "warnings" in data


def _first_content_hash() -> str:
    from safevault.db import connect

    conn = connect()
    try:
        return str(conn.execute("SELECT content_hash FROM versions").fetchone()["content_hash"])
    finally:
        conn.close()
