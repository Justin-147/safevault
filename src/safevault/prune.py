from __future__ import annotations

from pathlib import Path

from safevault.db import connect
from safevault.object_store import iter_object_hashes, object_path


def prune_unreferenced_objects(keep_days: int = 60, max_size: str = "50GB") -> tuple[int, int]:
    _ = (keep_days, max_size)
    conn = connect()
    try:
        referenced = {
            str(row["content_hash"])
            for row in conn.execute(
                "SELECT DISTINCT content_hash FROM versions WHERE content_hash IS NOT NULL"
            ).fetchall()
        }
    finally:
        conn.close()

    deleted = 0
    reclaimed = 0
    for content_hash in list(iter_object_hashes()):
        if content_hash in referenced:
            continue
        path = object_path(content_hash)
        if path.is_file():
            size = path.stat().st_size
            path.unlink()
            deleted += 1
            reclaimed += size
            _remove_empty_parents(path)
    return deleted, reclaimed


def _remove_empty_parents(path: Path) -> None:
    objects_root = object_path("0" * 64).parents[2]
    for parent in path.parents:
        if parent == objects_root:
            break
        try:
            parent.rmdir()
        except OSError:
            break
