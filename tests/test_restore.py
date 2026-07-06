from __future__ import annotations

from safevault.cli import app
from safevault.db import connect
from safevault.object_store import object_path
from safevault.restore import restore_file
from safevault.snapshot import create_snapshot


def test_delete_then_restore_latest_recreates_file(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    file_path.write_text("v2", encoding="utf-8")
    create_snapshot(project)
    file_path.unlink()
    create_snapshot(project)
    restore_file(file_path, latest=True)
    assert file_path.read_text(encoding="utf-8") == "v2"


def test_restore_specific_version_and_to_alternate_location(sv_home, project, tmp_path) -> None:
    file_path = project / "a.txt"
    file_path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    first_id = _version_ids()[0]
    file_path.write_text("v2", encoding="utf-8")
    create_snapshot(project)
    restore_file(file_path, version_id=first_id)
    assert file_path.read_text(encoding="utf-8") == "v1"
    target = tmp_path / "copy.txt"
    restore_file(file_path, version_id=first_id, to_path=target)
    assert target.read_text(encoding="utf-8") == "v1"


def test_deleted_marker_cannot_be_restored(runner, sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    file_path.unlink()
    create_snapshot(project)
    marker_id = _deleted_marker_id()
    result = runner.invoke(app, ["restore", str(file_path), "--version", str(marker_id)])
    assert result.exit_code != 0
    assert "deleted marker" in result.output


def test_existing_outside_target_is_preserved_before_overwrite(sv_home, project, tmp_path) -> None:
    file_path = project / "a.txt"
    file_path.write_text("vaulted", encoding="utf-8")
    create_snapshot(project)
    target = tmp_path / "target.txt"
    target.write_text("keep me", encoding="utf-8")
    restore_file(file_path, latest=True, to_path=target)
    backups = list(tmp_path.glob("target.txt.safevault-backup-*"))
    assert target.read_text(encoding="utf-8") == "vaulted"
    assert backups and backups[0].read_text(encoding="utf-8") == "keep me"


def test_missing_object_gives_clear_error(runner, sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    content_hash = _latest_hash()
    object_path(content_hash).unlink()
    result = runner.invoke(app, ["restore", str(file_path), "--latest"])
    assert result.exit_code != 0
    assert "missing" in result.output


def _version_ids() -> list[int]:
    conn = connect()
    try:
        return [int(row["id"]) for row in conn.execute("SELECT id FROM versions ORDER BY id")]
    finally:
        conn.close()


def _deleted_marker_id() -> int:
    conn = connect()
    try:
        return int(
            conn.execute("SELECT id FROM versions WHERE is_deleted_marker = 1").fetchone()["id"]
        )
    finally:
        conn.close()


def _latest_hash() -> str:
    conn = connect()
    try:
        return str(conn.execute("SELECT content_hash FROM versions ORDER BY id DESC").fetchone()[0])
    finally:
        conn.close()
