from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from safevault.db import connect
from safevault.object_store import is_valid_content_hash, object_path
from safevault.retention import RetentionPlan, SmartRetentionPolicy, build_smart_retention_plan


@dataclass(frozen=True)
class SmartCleanupDryRun:
    plan: RetentionPlan
    reclaimable_bytes: int
    reclaimable_objects: int
    important_snapshots: int
    protected_versions: int
    missing_objects: list[str]


def plan_smart_cleanup(
    *, now: datetime | None = None, policy: SmartRetentionPolicy | None = None
) -> SmartCleanupDryRun:
    plan = build_smart_retention_plan(now=now, policy=policy)
    candidate_version_ids = {item.version_id for item in plan.candidate_versions}
    conn = connect()
    try:
        important_snapshots = int(
            conn.execute(
                "SELECT COUNT(*) FROM restore_points WHERE important = 1"
            ).fetchone()[0]
        )
        protected_versions = _protected_version_count(conn, candidate_version_ids)
        reclaimable_hashes = _reclaimable_hashes(conn, candidate_version_ids)
    finally:
        conn.close()
    reclaimable_bytes = 0
    missing_objects: list[str] = []
    for content_hash in sorted(reclaimable_hashes):
        path = object_path(content_hash)
        try:
            reclaimable_bytes += path.stat().st_size
        except OSError:
            missing_objects.append(content_hash)
    return SmartCleanupDryRun(
        plan=plan,
        reclaimable_bytes=reclaimable_bytes,
        reclaimable_objects=len(reclaimable_hashes) - len(missing_objects),
        important_snapshots=important_snapshots,
        protected_versions=protected_versions,
        missing_objects=missing_objects,
    )


def dry_run_smart_cleanup(
    *, now: datetime | None = None, policy: SmartRetentionPolicy | None = None
) -> SmartCleanupDryRun:
    return plan_smart_cleanup(now=now, policy=policy)


def _protected_version_count(conn, candidate_version_ids: set[int]) -> int:
    total = int(conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0])
    return total - len(candidate_version_ids)


def _reclaimable_hashes(conn, candidate_version_ids: set[int]) -> set[str]:
    if not candidate_version_ids:
        return set()
    placeholders = ",".join("?" for _ in candidate_version_ids)
    candidate_hashes = {
        str(row["content_hash"])
        for row in conn.execute(
            f"""
            SELECT DISTINCT content_hash
            FROM versions
            WHERE id IN ({placeholders})
              AND content_hash IS NOT NULL
            """,
            tuple(candidate_version_ids),
        ).fetchall()
        if is_valid_content_hash(str(row["content_hash"]))
    }
    if not candidate_hashes:
        return set()
    still_referenced = {
        str(row["content_hash"])
        for row in conn.execute(
            f"""
            SELECT DISTINCT content_hash
            FROM versions
            WHERE id NOT IN ({placeholders})
              AND content_hash IS NOT NULL
            """,
            tuple(candidate_version_ids),
        ).fetchall()
        if is_valid_content_hash(str(row["content_hash"]))
    }
    return candidate_hashes - still_referenced
