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


def test_doctor_reports_corrupted_referenced_object(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    digest = _first_content_hash()
    object_path(digest).write_text("corrupt", encoding="utf-8")
    result = run_doctor(deep=True)
    assert not result.healthy
    assert digest in result.corrupted_objects


def test_doctor_fast_does_not_rehash_existing_objects(sv_home, project, monkeypatch) -> None:
    path = project / "a.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)

    def fail_verify(_content_hash: str) -> bool:
        raise AssertionError("fast doctor should not verify object content")

    monkeypatch.setattr("safevault.doctor.verify_object", fail_verify)
    result = run_doctor()
    assert result.healthy
    assert result.corrupted_objects == []


def test_doctor_reports_invalid_reference(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    _set_first_content_hash("not-a-hash")
    result = run_doctor()
    assert not result.healthy
    assert result.invalid_references == ["not-a-hash"]


def test_doctor_json_includes_invalid_references(runner, sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    _set_first_content_hash("not-a-hash")
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["invalid_references"] == ["not-a-hash"]


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


def _set_first_content_hash(value: str) -> None:
    from safevault.db import connect

    conn = connect()
    try:
        conn.execute("UPDATE versions SET content_hash = ? WHERE id = 1", (value,))
        conn.commit()
    finally:
        conn.close()
