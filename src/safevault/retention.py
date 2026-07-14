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


@dataclass(frozen=True)
class SmartRetentionPolicy:
    high_frequency_hours: int = 4
    hourly_days: int = 7
    daily_days: int = 30


def build_retention_plan(
    *, keep_days: int, now: datetime | None = None
) -> RetentionPlan:
    conn = connect()
    try:
        return _build_retention_plan(conn, keep_days=keep_days, now=now)
    finally:
        conn.close()


def _build_retention_plan(conn, *, keep_days: int, now: datetime | None = None) -> RetentionPlan:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=keep_days)
    protected_versions: set[int] = set()
    for file_row in conn.execute("SELECT id FROM files").fetchall():
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

    protected_snapshots = {
        int(row["snapshot_id"])
        for row in conn.execute(
            "SELECT snapshot_id FROM restore_points WHERE important = 1"
        ).fetchall()
    }
    protected_snapshots.update(
        int(snapshot_id)
        for row in conn.execute(
            "SELECT before_snapshot_id, after_snapshot_id FROM ai_change_sessions"
        ).fetchall()
        for snapshot_id in (row["before_snapshot_id"], row["after_snapshot_id"])
        if snapshot_id is not None
    )

    candidates: list[RetentionVersionCandidate] = []
    candidate_version_ids: set[int] = set()
    version_rows = conn.execute(
        """
        SELECT id, snapshot_id, rel_path, captured_at, is_deleted_marker
        FROM versions
        ORDER BY id
        """
    ).fetchall()
    for row in version_rows:
        version_id = int(row["id"])
        if (
            version_id in protected_versions
            or int(row["snapshot_id"]) in protected_snapshots
            or int(row["is_deleted_marker"])
        ):
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
        if (
            snapshot_id in protected_snapshots
            or _parse_iso_datetime(str(row["started_at"])) >= cutoff
        ):
            continue
        snapshot_version_ids = {
            int(version["id"])
            for version in conn.execute(
                "SELECT id FROM versions WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchall()
        }
        if snapshot_version_ids and snapshot_version_ids <= candidate_version_ids:
            candidate_snapshots.append(snapshot_id)
    return RetentionPlan(
        candidate_versions=candidates,
        candidate_snapshots=candidate_snapshots,
    )


def build_smart_retention_plan(
    *, now: datetime | None = None, policy: SmartRetentionPolicy | None = None
) -> RetentionPlan:
    current = datetime.now(UTC) if now is None else now
    retention = policy or SmartRetentionPolicy()
    high_frequency_cutoff = current - timedelta(hours=retention.high_frequency_hours)
    hourly_cutoff = current - timedelta(days=retention.hourly_days)
    daily_cutoff = current - timedelta(days=retention.daily_days)
    conn = connect()
    try:
        protected_versions = _latest_active_versions(conn)
        important_snapshots = {
            int(row["snapshot_id"])
            for row in conn.execute(
                "SELECT snapshot_id FROM restore_points WHERE important = 1"
            ).fetchall()
        }
        hourly_kept: set[tuple[int, str]] = set()
        daily_kept: set[tuple[int, str]] = set()
        candidates: list[RetentionVersionCandidate] = []
        candidate_version_ids: set[int] = set()
        rows = conn.execute(
            """
            SELECT id, file_id, snapshot_id, rel_path, captured_at, is_deleted_marker
            FROM versions
            ORDER BY captured_at DESC, id DESC
            """
        ).fetchall()
        for row in rows:
            version_id = int(row["id"])
            snapshot_id = int(row["snapshot_id"])
            file_id = int(row["file_id"])
            captured_at = _parse_iso_datetime(str(row["captured_at"]))
            if (
                version_id in protected_versions
                or int(row["is_deleted_marker"])
                or snapshot_id in important_snapshots
                or captured_at >= high_frequency_cutoff
            ):
                continue
            if captured_at >= hourly_cutoff:
                bucket = (file_id, captured_at.strftime("%Y-%m-%dT%H"))
                if bucket not in hourly_kept:
                    hourly_kept.add(bucket)
                    continue
            elif captured_at >= daily_cutoff:
                bucket = (file_id, captured_at.strftime("%Y-%m-%d"))
                if bucket not in daily_kept:
                    daily_kept.add(bucket)
                    continue
            candidates.append(
                RetentionVersionCandidate(
                    version_id=version_id,
                    rel_path=str(row["rel_path"]),
                    captured_at=str(row["captured_at"]),
                )
            )
            candidate_version_ids.add(version_id)
        candidate_snapshots = _candidate_snapshots(
            conn, candidate_version_ids, important_snapshots
        )
    finally:
        conn.close()
    return RetentionPlan(candidate_versions=candidates, candidate_snapshots=candidate_snapshots)


def _latest_active_versions(conn) -> set[int]:
    protected_versions: set[int] = set()
    for file_row in conn.execute("SELECT id FROM files").fetchall():
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
    return protected_versions


def _candidate_snapshots(
    conn, candidate_version_ids: set[int], important_snapshots: set[int]
) -> list[int]:
    candidate_snapshots: list[int] = []
    for row in conn.execute("SELECT id FROM snapshots").fetchall():
        snapshot_id = int(row["id"])
        if snapshot_id in important_snapshots:
            continue
        snapshot_version_ids = {
            int(version["id"])
            for version in conn.execute(
                "SELECT id FROM versions WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchall()
        }
        if snapshot_version_ids and snapshot_version_ids <= candidate_version_ids:
            candidate_snapshots.append(snapshot_id)
    return candidate_snapshots


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
