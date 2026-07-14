from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from safevault.config import SafeVaultConfig, load_config, save_config
from safevault.db import connect
from safevault.errors import SafeVaultError
from safevault.object_store import is_valid_content_hash, object_path
from safevault.retention import RetentionPlan, _build_retention_plan

AUTO_CLEANUP_CONFIRMATION = "ENABLE AUTO CLEANUP"
AUTO_CLEANUP_INTERVAL = timedelta(days=1)
_SQL_CHUNK_SIZE = 500


@dataclass(frozen=True)
class RetentionCleanupPreview:
    plan: RetentionPlan
    reclaimable_objects: int
    reclaimable_bytes: int


@dataclass(frozen=True)
class RetentionCleanupResult:
    deleted_versions: int
    deleted_snapshots: int
    deleted_objects: int
    reclaimed_bytes: int
    completed_at: str


def configure_retention(
    *, keep_days: int, auto_cleanup_enabled: bool, confirmation: str = ""
) -> SafeVaultConfig:
    if keep_days < 1 or keep_days > 3650:
        raise SafeVaultError("retention days must be between 1 and 3650")
    config = load_config()
    requires_confirmation = auto_cleanup_enabled and (
        not config.retention.auto_cleanup_enabled
        or keep_days < config.retention.keep_days
    )
    if requires_confirmation and confirmation != AUTO_CLEANUP_CONFIRMATION:
        raise SafeVaultError(
            f"type {AUTO_CLEANUP_CONFIRMATION} to enable or shorten automatic cleanup"
        )
    reset_due_time = requires_confirmation or (
        auto_cleanup_enabled and not config.retention.auto_cleanup_enabled
    )
    retention = replace(
        config.retention,
        keep_days=keep_days,
        auto_cleanup_enabled=auto_cleanup_enabled,
        last_cleanup_at=None if reset_due_time else config.retention.last_cleanup_at,
        last_cleanup_status=(
            "pending" if reset_due_time else config.retention.last_cleanup_status
        ),
        last_cleanup_error=None if reset_due_time else config.retention.last_cleanup_error,
    )
    updated = replace(config, retention=retention)
    save_config(updated)
    return updated


def preview_retention_cleanup(
    *, keep_days: int, now: datetime | None = None
) -> RetentionCleanupPreview:
    conn = connect()
    try:
        plan = _build_retention_plan(conn, keep_days=keep_days, now=now)
        reclaimable_hashes = _candidate_reclaimable_hashes(conn, plan)
    finally:
        conn.close()
    reclaimable_bytes = 0
    reclaimable_objects = 0
    for content_hash in reclaimable_hashes:
        path = object_path(content_hash)
        if path.is_symlink() or not path.is_file():
            continue
        try:
            reclaimable_bytes += path.stat().st_size
        except OSError:
            continue
        reclaimable_objects += 1
    return RetentionCleanupPreview(
        plan=plan,
        reclaimable_objects=reclaimable_objects,
        reclaimable_bytes=reclaimable_bytes,
    )


def apply_retention_cleanup(
    *, keep_days: int, allow_delete: bool = False, now: datetime | None = None
) -> RetentionCleanupResult:
    if not allow_delete:
        raise SafeVaultError("retention cleanup requires --allow-delete authorization")
    current = now or datetime.now(UTC)
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        plan = _build_retention_plan(conn, keep_days=keep_days, now=current)
        version_ids = [item.version_id for item in plan.candidate_versions]
        snapshot_ids = plan.candidate_snapshots
        reclaimable_hashes = _candidate_reclaimable_hashes(conn, plan)

        _delete_in_chunks(conn, "version_timeline", "version_id", version_ids)
        _delete_in_chunks(conn, "versions", "id", version_ids)
        _set_null_in_chunks(conn, "file_events", "snapshot_id", snapshot_ids)
        _set_null_in_chunks(conn, "change_batches", "snapshot_id", snapshot_ids)
        _delete_nonimportant_restore_points(conn, snapshot_ids)
        _delete_in_chunks(conn, "snapshots", "id", snapshot_ids)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    deleted_objects, reclaimed_bytes = _delete_unreferenced_candidates(
        reclaimable_hashes
    )
    return RetentionCleanupResult(
        deleted_versions=len(version_ids),
        deleted_snapshots=len(snapshot_ids),
        deleted_objects=deleted_objects,
        reclaimed_bytes=reclaimed_bytes,
        completed_at=current.isoformat(timespec="microseconds"),
    )


def run_due_retention_cleanup(
    *, now: datetime | None = None
) -> RetentionCleanupResult | None:
    current = now or datetime.now(UTC)
    config = load_config()
    if not config.retention.auto_cleanup_enabled:
        return None
    last_cleanup = _parse_optional_iso(config.retention.last_cleanup_at)
    if last_cleanup is not None and current - last_cleanup < AUTO_CLEANUP_INTERVAL:
        return None
    try:
        result = apply_retention_cleanup(
            keep_days=config.retention.keep_days,
            allow_delete=True,
            now=current,
        )
    except (OSError, sqlite3.Error, SafeVaultError) as exc:
        _record_cleanup_status(
            current=current,
            status="failed",
            deleted_versions=0,
            reclaimed_bytes=0,
            error=str(exc),
        )
        return None
    _record_cleanup_status(
        current=current,
        status="success",
        deleted_versions=result.deleted_versions,
        reclaimed_bytes=result.reclaimed_bytes,
        error=None,
    )
    return result


def _candidate_reclaimable_hashes(conn, plan: RetentionPlan) -> set[str]:
    version_ids = [item.version_id for item in plan.candidate_versions]
    if not version_ids:
        return set()
    candidate_hashes: set[str] = set()
    for chunk in _chunks(version_ids):
        placeholders = ",".join("?" for _ in chunk)
        candidate_hashes.update(
            str(row["content_hash"])
            for row in conn.execute(
                f"""
                SELECT DISTINCT content_hash FROM versions
                WHERE id IN ({placeholders}) AND content_hash IS NOT NULL
                """,
                chunk,
            ).fetchall()
            if is_valid_content_hash(str(row["content_hash"]))
        )
    if not candidate_hashes:
        return set()
    candidate_id_set = set(version_ids)
    still_referenced = {
        str(row["content_hash"])
        for row in conn.execute(
            "SELECT id, content_hash FROM versions WHERE content_hash IS NOT NULL"
        ).fetchall()
        if str(row["content_hash"]) in candidate_hashes
        and int(row["id"]) not in candidate_id_set
    }
    return candidate_hashes - still_referenced


def _delete_unreferenced_candidates(content_hashes: set[str]) -> tuple[int, int]:
    if not content_hashes:
        return 0, 0
    conn = connect()
    try:
        # Hold the writer lock through object deletion so a concurrent snapshot
        # cannot add a new reference between the final check and unlink.
        conn.execute("BEGIN IMMEDIATE")
        still_referenced = {
            str(row["content_hash"])
            for row in conn.execute(
                "SELECT DISTINCT content_hash FROM versions WHERE content_hash IS NOT NULL"
            ).fetchall()
            if str(row["content_hash"]) in content_hashes
        }
        deleted = 0
        reclaimed = 0
        for content_hash in content_hashes - still_referenced:
            path = object_path(content_hash)
            if path.is_symlink() or not path.is_file():
                continue
            try:
                size = path.stat().st_size
                path.unlink()
            except OSError:
                continue
            deleted += 1
            reclaimed += size
        conn.commit()
        return deleted, reclaimed
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _delete_in_chunks(conn, table: str, column: str, values: list[int]) -> None:
    for chunk in _chunks(values):
        placeholders = ",".join("?" for _ in chunk)
        conn.execute(f"DELETE FROM {table} WHERE {column} IN ({placeholders})", chunk)


def _set_null_in_chunks(conn, table: str, column: str, values: list[int]) -> None:
    for chunk in _chunks(values):
        placeholders = ",".join("?" for _ in chunk)
        conn.execute(
            f"UPDATE {table} SET {column} = NULL WHERE {column} IN ({placeholders})",
            chunk,
        )


def _delete_nonimportant_restore_points(conn, snapshot_ids: list[int]) -> None:
    for chunk in _chunks(snapshot_ids):
        placeholders = ",".join("?" for _ in chunk)
        conn.execute(
            f"""
            DELETE FROM restore_points
            WHERE important = 0 AND snapshot_id IN ({placeholders})
            """,
            chunk,
        )


def _chunks(values: list[int]) -> list[tuple[int, ...]]:
    return [
        tuple(values[index : index + _SQL_CHUNK_SIZE])
        for index in range(0, len(values), _SQL_CHUNK_SIZE)
    ]


def _record_cleanup_status(
    *,
    current: datetime,
    status: str,
    deleted_versions: int,
    reclaimed_bytes: int,
    error: str | None,
) -> None:
    config = load_config()
    retention = replace(
        config.retention,
        last_cleanup_at=current.isoformat(timespec="microseconds"),
        last_cleanup_status=status,
        last_cleanup_deleted_versions=deleted_versions,
        last_cleanup_reclaimed_bytes=reclaimed_bytes,
        last_cleanup_error=error,
    )
    save_config(replace(config, retention=retention))


def _parse_optional_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
