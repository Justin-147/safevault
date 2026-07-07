from __future__ import annotations

from safevault.object_store import object_path, store_bytes
from safevault.prune import prune_unreferenced_objects
from safevault.snapshot import create_snapshot


def test_prune_deletes_unreferenced_object(sv_home) -> None:
    digest = store_bytes(b"orphan")
    deleted, _ = prune_unreferenced_objects()
    assert deleted == 1
    assert not object_path(digest).exists()


def test_prune_keeps_referenced_object(sv_home, project) -> None:
    (project / "a.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    digest = _first_content_hash()
    deleted, _ = prune_unreferenced_objects()
    assert deleted == 0
    assert object_path(digest).exists()


def test_prune_dry_run_deletes_nothing(sv_home) -> None:
    digest = store_bytes(b"orphan")
    deleted, _ = prune_unreferenced_objects(dry_run=True)
    assert deleted == 1
    assert object_path(digest).exists()


def _first_content_hash() -> str:
    from safevault.db import connect

    conn = connect()
    try:
        return str(conn.execute("SELECT content_hash FROM versions").fetchone()["content_hash"])
    finally:
        conn.close()
