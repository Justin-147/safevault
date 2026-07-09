from __future__ import annotations

from datetime import UTC, datetime

from safevault.db import connect
from safevault.object_store import store_bytes
from safevault.retention_engine import dry_run_smart_cleanup


def test_smart_cleanup_dry_run_estimates_unique_reclaimable_objects(
    sv_home, project
) -> None:
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    old_hash = store_bytes(b"old-object")
    latest_hash = store_bytes(b"latest")
    conn = connect()
    try:
        root_id, file_id = _insert_root_and_file(conn, project, latest_hash, now)
        _insert_version(conn, root_id, file_id, old_hash, datetime(2026, 5, 1, tzinfo=UTC))
        _insert_version(conn, root_id, file_id, old_hash, datetime(2026, 5, 2, tzinfo=UTC))
        _insert_version(conn, root_id, file_id, latest_hash, now)
        conn.commit()
    finally:
        conn.close()

    result = dry_run_smart_cleanup(now=now)

    assert len(result.plan.candidate_versions) == 2
    assert result.reclaimable_objects == 1
    assert result.reclaimable_bytes == len(b"old-object")
    assert result.missing_objects == []


def test_smart_cleanup_does_not_count_objects_referenced_by_important_versions(
    sv_home, project
) -> None:
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    shared_hash = store_bytes(b"shared")
    latest_hash = store_bytes(b"latest")
    conn = connect()
    try:
        root_id, file_id = _insert_root_and_file(conn, project, latest_hash, now)
        important_snapshot = _insert_version(
            conn, root_id, file_id, shared_hash, datetime(2026, 5, 1, tzinfo=UTC)
        )
        _insert_important_restore_point(conn, root_id, important_snapshot)
        _insert_version(conn, root_id, file_id, shared_hash, datetime(2026, 5, 2, tzinfo=UTC))
        _insert_version(conn, root_id, file_id, latest_hash, now)
        conn.commit()
    finally:
        conn.close()

    result = dry_run_smart_cleanup(now=now)

    assert len(result.plan.candidate_versions) == 1
    assert result.reclaimable_objects == 0
    assert result.reclaimable_bytes == 0
    assert result.important_snapshots == 1


def _insert_root_and_file(conn, project, latest_hash: str, now: datetime) -> tuple[int, int]:
    root_id = int(
        conn.execute(
            "INSERT INTO roots(path, created_at, profile) VALUES (?, ?, 'coding')",
            (str(project), now.isoformat()),
        ).lastrowid
    )
    file_id = int(
        conn.execute(
            """
            INSERT INTO files(
                root_id, rel_path, file_kind, current_hash, size, mtime_ns, mode,
                last_seen_at, status
            )
            VALUES (?, 'doc.txt', 'file', ?, 1, 1, 0, ?, 'active')
            """,
            (root_id, latest_hash, now.isoformat()),
        ).lastrowid
    )
    return root_id, file_id


def _insert_version(conn, root_id: int, file_id: int, content_hash: str, at: datetime) -> int:
    snapshot_id = int(
        conn.execute(
            """
            INSERT INTO snapshots(root_id, reason, label, started_at, finished_at, status)
            VALUES (?, 'test', NULL, ?, ?, 'complete')
            """,
            (root_id, at.isoformat(), at.isoformat()),
        ).lastrowid
    )
    conn.execute(
        """
        INSERT INTO versions(
            file_id, snapshot_id, rel_path, content_hash, size, mtime_ns,
            mode, captured_at, is_deleted_marker
        )
        VALUES (?, ?, 'doc.txt', ?, 1, 1, 0, ?, 0)
        """,
        (file_id, snapshot_id, content_hash, at.isoformat()),
    )
    return snapshot_id


def _insert_important_restore_point(conn, root_id: int, snapshot_id: int) -> None:
    conn.execute(
        """
        INSERT INTO restore_points(
            root_id, snapshot_id, label, reason, created_at, source, important
        )
        VALUES (?, ?, 'important', 'checkpoint', '2026-05-01T00:00:00+00:00', 'test', 1)
        """,
        (root_id, snapshot_id),
    )
