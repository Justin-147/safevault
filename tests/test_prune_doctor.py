from __future__ import annotations

import shutil

from safevault.doctor import run_doctor
from safevault.object_store import object_path, store_bytes
from safevault.prune import prune_unreferenced_objects
from safevault.snapshot import create_snapshot


def test_prune_deletes_unreferenced_object(sv_home) -> None:
    digest = store_bytes(b"orphan")
    deleted, reclaimed = prune_unreferenced_objects()
    assert deleted == 1
    assert reclaimed == len(b"orphan")
    assert not object_path(digest).exists()


def test_prune_does_not_delete_referenced_object(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    digest = _only_hash()
    deleted, _ = prune_unreferenced_objects()
    assert deleted == 0
    assert object_path(digest).is_file()


def test_doctor_detects_missing_referenced_object(sv_home, project) -> None:
    file_path = project / "a.txt"
    file_path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    digest = _only_hash()
    object_path(digest).unlink()
    result = run_doctor()
    assert digest in result.missing_objects
    assert not result.healthy


def test_doctor_detects_orphan_object(sv_home) -> None:
    digest = store_bytes(b"orphan")
    result = run_doctor()
    assert digest in result.orphan_objects


def test_doctor_detects_missing_root_path(sv_home, project) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    shutil.rmtree(project)
    result = run_doctor()
    assert str(project.resolve()) in result.missing_roots


def _only_hash() -> str:
    from safevault.db import connect

    conn = connect()
    try:
        return str(conn.execute("SELECT content_hash FROM versions").fetchone()["content_hash"])
    finally:
        conn.close()
