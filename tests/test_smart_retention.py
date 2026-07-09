from __future__ import annotations

from datetime import UTC, datetime

from safevault.db import connect
from safevault.retention import build_smart_retention_plan


def test_smart_retention_keeps_recent_hourly_daily_latest_and_important(
    sv_home, project
) -> None:
    now = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)
    conn = connect()
    try:
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
                VALUES (?, 'doc.txt', 'file', 'latest', 1, 1, 0, ?, 'active')
                """,
                (root_id, now.isoformat()),
            ).lastrowid
        )
        version_times = [
            datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
            datetime(2026, 6, 29, 9, 0, tzinfo=UTC),
            datetime(2026, 6, 29, 18, 0, tzinfo=UTC),
            datetime(2026, 7, 8, 10, 0, tzinfo=UTC),
            datetime(2026, 7, 8, 10, 30, tzinfo=UTC),
            datetime(2026, 7, 9, 11, 0, tzinfo=UTC),
        ]
        version_ids = []
        for index, captured_at in enumerate(version_times, start=1):
            snapshot_id = int(
                conn.execute(
                    """
                    INSERT INTO snapshots(root_id, reason, label, started_at, finished_at, status)
                    VALUES (?, 'test', NULL, ?, ?, 'complete')
                    """,
                    (root_id, captured_at.isoformat(), captured_at.isoformat()),
                ).lastrowid
            )
            version_id = int(
                conn.execute(
                    """
                    INSERT INTO versions(
                        file_id, snapshot_id, rel_path, content_hash, size, mtime_ns,
                        mode, captured_at, is_deleted_marker
                    )
                    VALUES (?, ?, 'doc.txt', ?, 1, 1, 0, ?, 0)
                    """,
                    (file_id, snapshot_id, f"hash-{index}", captured_at.isoformat()),
                ).lastrowid
            )
            version_ids.append(version_id)
            if index == 1:
                conn.execute(
                    """
                    INSERT INTO restore_points(
                        root_id, snapshot_id, label, reason, created_at, source, important
                    )
                    VALUES (?, ?, 'important', 'checkpoint', ?, 'test', 1)
                    """,
                    (root_id, snapshot_id, captured_at.isoformat()),
                )
        conn.commit()
    finally:
        conn.close()

    plan = build_smart_retention_plan(now=now)

    candidate_ids = {item.version_id for item in plan.candidate_versions}
    assert version_ids[0] not in candidate_ids
    assert version_ids[1] in candidate_ids
    assert version_ids[2] not in candidate_ids
    assert version_ids[3] in candidate_ids
    assert version_ids[4] not in candidate_ids
    assert version_ids[5] not in candidate_ids
