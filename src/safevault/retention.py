from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from safevault.db import connect


@dataclass(frozen=True)
class RetentionVersionCandidate:
    version_id: int
    rel_path: str
    captured_at: str


@dataclass(frozen=True)
class RetentionPlan:
    candidate_versions: list[RetentionVersionCandidate]
    candidate_snapshots: list[int]


def build_retention_plan(*, keep_days: int) -> RetentionPlan:
    cutoff = datetime.now(UTC) - timedelta(days=keep_days)
    conn = connect()
    try:
        file_rows = conn.execute("SELECT id, status FROM files").fetchall()
        protected_versions: set[int] = set()
        for file_row in file_rows:
            row = conn.execute(
                """
                SELECT id FROM versions
                WHERE file_id = ? AND is_deleted_marker = 0
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(file_row["id"]),),
            ).fetchone()
            if row is not None:
                protected_versions.add(int(row["id"]))

        version_rows = conn.execute(
            """
            SELECT id, snapshot_id, rel_path, captured_at, is_deleted_marker
            FROM versions
            ORDER BY id
            """
        ).fetchall()
        candidates: list[RetentionVersionCandidate] = []
        candidate_version_ids: set[int] = set()
        for row in version_rows:
            version_id = int(row["id"])
            if version_id in protected_versions or int(row["is_deleted_marker"]):
                continue
            if _parse_iso_datetime(str(row["captured_at"])) >= cutoff:
                continue
            candidates.append(
                RetentionVersionCandidate(
                    version_id=version_id,
                    rel_path=str(row["rel_path"]),
                    captured_at=str(row["captured_at"]),
                )
            )
            candidate_version_ids.add(version_id)

        candidate_snapshots: list[int] = []
        for row in conn.execute("SELECT id, started_at FROM snapshots").fetchall():
            snapshot_id = int(row["id"])
            if _parse_iso_datetime(str(row["started_at"])) >= cutoff:
                continue
            snapshot_version_ids = {
                int(version["id"])
                for version in conn.execute(
                    "SELECT id FROM versions WHERE snapshot_id = ?", (snapshot_id,)
                ).fetchall()
            }
            if snapshot_version_ids and snapshot_version_ids <= candidate_version_ids:
                candidate_snapshots.append(snapshot_id)
    finally:
        conn.close()
    return RetentionPlan(candidate_versions=candidates, candidate_snapshots=candidate_snapshots)


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
