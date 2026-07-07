from __future__ import annotations

import json
import sqlite3
import tarfile

from safevault.cli import app
from safevault.object_store import object_path
from safevault.paths import get_tmp_dir
from safevault.snapshot import create_snapshot


def test_export_creates_archive_with_db_objects_and_manifest(
    runner, sv_home, project, tmp_path
) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = tmp_path / "safevault-export.tar"
    result = runner.invoke(app, ["export", "--output", str(output)])
    assert result.exit_code == 0
    with tarfile.open(output) as archive:
        names = archive.getnames()
        assert "vault.db" in names
        assert "manifest.json" in names
        assert any(name.startswith("objects/") for name in names)
        manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
    assert manifest["object_count"] == 1
    assert manifest["database"] == "vault.db"
    assert manifest["schema_version"] == 1
    assert manifest["verified"] is True
    assert manifest["database_backup"] is True
    assert manifest["compression"] == "none"


def test_export_uses_consistent_sqlite_backup(runner, sv_home, project, tmp_path) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = tmp_path / "safevault-export.tar"
    result = runner.invoke(app, ["export", "--output", str(output)])
    assert result.exit_code == 0
    db_copy = tmp_path / "vault.db"
    with tarfile.open(output) as archive:
        db_copy.write_bytes(archive.extractfile("vault.db").read())
    conn = sqlite3.connect(db_copy)
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"roots", "files", "versions"} <= tables
        assert int(conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0]) >= 1
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def test_export_archive_db_is_readable_without_wal_file(runner, sv_home, project, tmp_path) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = tmp_path / "safevault-export.tar"
    result = runner.invoke(app, ["export", "--output", str(output)])
    assert result.exit_code == 0
    db_copy = tmp_path / "vault.db"
    with tarfile.open(output) as archive:
        db_copy.write_bytes(archive.extractfile("vault.db").read())
    conn = sqlite3.connect(db_copy)
    try:
        assert conn.execute("SELECT COUNT(*) FROM roots").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0] == 1
    finally:
        conn.close()


def test_export_excludes_tmp_and_partial_files(runner, sv_home, project, tmp_path) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    tmp_file = get_tmp_dir() / "leftover.partial"
    tmp_file.write_text("partial", encoding="utf-8")
    output = tmp_path / "safevault-export.tar.gz"
    result = runner.invoke(app, ["export", "--output", str(output), "--gzip"])
    assert result.exit_code == 0
    with tarfile.open(output, "r:gz") as archive:
        assert "tmp/leftover.partial" not in archive.getnames()


def test_export_refuses_output_inside_vault_home(runner, sv_home, project) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = sv_home / "export.tar"
    result = runner.invoke(app, ["export", "--output", str(output)])
    assert result.exit_code != 0
    assert "inside SAFEVAULT_HOME" in result.output


def test_export_allows_output_inside_vault_home_with_flag(runner, sv_home, project) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = sv_home / "export.tar"
    result = runner.invoke(
        app, ["export", "--output", str(output), "--allow-inside-vault"]
    )
    assert result.exit_code == 0
    assert output.exists()


def test_export_refuses_to_overwrite_existing_file_without_overwrite(
    runner, sv_home, project, tmp_path
) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = tmp_path / "export.tar"
    output.write_text("keep", encoding="utf-8")
    result = runner.invoke(app, ["export", "--output", str(output)])
    assert result.exit_code != 0
    assert output.read_text(encoding="utf-8") == "keep"


def test_export_overwrite_replaces_existing_file_with_flag(
    runner, sv_home, project, tmp_path
) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = tmp_path / "export.tar"
    output.write_text("old", encoding="utf-8")
    result = runner.invoke(app, ["export", "--output", str(output), "--overwrite"])
    assert result.exit_code == 0
    assert output.read_bytes() != b"old"


def test_export_fails_on_missing_referenced_object(runner, sv_home, project, tmp_path) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    digest = _first_hash()
    object_path(digest).unlink()
    output = tmp_path / "export.tar"
    result = runner.invoke(app, ["export", "--output", str(output)])
    assert result.exit_code != 0
    assert not output.exists()


def test_export_fails_on_corrupted_referenced_object_by_default(
    runner, sv_home, project, tmp_path
) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    object_path(_first_hash()).write_bytes(b"corrupt")
    output = tmp_path / "export.tar"
    result = runner.invoke(app, ["export", "--output", str(output)])
    assert result.exit_code != 0
    assert not output.exists()


def test_export_skip_verify_allows_corrupted_object_archive_only_when_explicit(
    runner, sv_home, project, tmp_path
) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    object_path(_first_hash()).write_bytes(b"corrupt")
    output = tmp_path / "export.tar"
    result = runner.invoke(app, ["export", "--output", str(output), "--skip-verify"])
    assert result.exit_code == 0
    with tarfile.open(output) as archive:
        manifest = json.loads(archive.extractfile("manifest.json").read().decode("utf-8"))
    assert manifest["verified"] is False


def test_failed_export_leaves_existing_output_unchanged(
    runner, sv_home, project, tmp_path
) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    object_path(_first_hash()).write_bytes(b"corrupt")
    output = tmp_path / "export.tar"
    output.write_bytes(b"keep")
    result = runner.invoke(app, ["export", "--output", str(output), "--overwrite"])
    assert result.exit_code != 0
    assert output.read_bytes() == b"keep"


def _first_hash() -> str:
    from safevault.db import connect

    conn = connect()
    try:
        return str(conn.execute("SELECT content_hash FROM versions").fetchone()["content_hash"])
    finally:
        conn.close()
