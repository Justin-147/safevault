from __future__ import annotations

import os

from conftest import make_symlink_or_skip
from safevault.db import connect
from safevault.snapshot import create_snapshot


def _count_versions() -> int:
    conn = connect()
    try:
        return int(conn.execute("SELECT COUNT(*) AS c FROM versions").fetchone()["c"])
    finally:
        conn.close()


def test_snapshot_new_unchanged_modified_and_deleted_file(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    assert _count_versions() == 1

    create_snapshot(project)
    assert _count_versions() == 1

    file_path.write_text("v2", encoding="utf-8")
    create_snapshot(project)
    assert _count_versions() == 2

    file_path.unlink()
    create_snapshot(project)
    conn = connect()
    try:
        file_row = conn.execute("SELECT * FROM files WHERE rel_path = 'a.txt'").fetchone()
        marker = conn.execute(
            "SELECT * FROM versions WHERE is_deleted_marker = 1"
        ).fetchone()
    finally:
        conn.close()
    assert file_row["status"] == "deleted"
    assert marker["content_hash"] is None


def test_ignored_files_are_not_tracked(sv_home, project) -> None:
    (project / "debug.log").write_text("ignore", encoding="utf-8")
    (project / "src.py").write_text("track", encoding="utf-8")
    create_snapshot(project)
    conn = connect()
    try:
        rels = {row["rel_path"] for row in conn.execute("SELECT rel_path FROM files")}
    finally:
        conn.close()
    assert "src.py" in rels
    assert "debug.log" not in rels


def test_symlink_is_tracked_without_following_outside_root(sv_home, project, tmp_path) -> None:
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("secret outside", encoding="utf-8")
    link = project / "outside-link"
    make_symlink_or_skip(outside, link)
    create_snapshot(project)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM files WHERE rel_path = ?", (link.name,)).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["file_kind"] == "symlink"
    assert os.path.getsize(outside) != row["size"]
