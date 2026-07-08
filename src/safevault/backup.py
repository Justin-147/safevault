from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from safevault.atomic import atomic_copy_file
from safevault.config import (
    BackupSchedule,
    SafeVaultConfig,
    load_config,
    save_config,
    validate_backup_target,
    with_backup,
)
from safevault.db import connect, list_roots, utc_now_iso
from safevault.errors import SafeVaultError
from safevault.exporter import ExportResult, export_vault

BACKUP_FAILURE_RETRY_INTERVAL = timedelta(hours=1)


@dataclass(frozen=True)
class BackupStatus:
    enabled: bool
    target: str | None
    schedule: str
    last_success_at: str | None
    last_failure_at: str | None
    last_error: str | None
    latest_archive: str | None
    latest_object_count: int | None
    time: str
    next_due_at: str | None


def configure_backup(
    target: Path,
    schedule: BackupSchedule = "daily",
    *,
    time: str | None = None,
) -> SafeVaultConfig:
    target_path = target.expanduser().resolve(strict=False)
    conn = connect()
    try:
        roots = [Path(root.path) for root in list_roots(conn)]
    finally:
        conn.close()
    validate_backup_target(str(target_path), protected_roots=roots)
    target_path.mkdir(parents=True, exist_ok=True)
    config = with_backup(
        load_config(),
        target=target_path,
        schedule=schedule,
        time=time,
        enabled=True,
    )
    save_config(config)
    return config


def disable_backup() -> SafeVaultConfig:
    config = with_backup(load_config(), enabled=False)
    save_config(config)
    return config


def get_backup_status() -> BackupStatus:
    config = load_config()
    conn = connect()
    try:
        success = conn.execute(
            """
            SELECT * FROM backup_jobs
            WHERE status = 'success'
            ORDER BY finished_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        failure = conn.execute(
            """
            SELECT * FROM backup_jobs
            WHERE status = 'failed'
            ORDER BY finished_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    last_success_at = None if success is None else str(success["finished_at"])
    next_due = next_due_after(
        _parse_iso(last_success_at) if last_success_at is not None else None,
        config.backup.schedule,
        config.backup.time,
        datetime.now(UTC),
    )
    return BackupStatus(
        enabled=config.backup.enabled,
        target=config.backup.target,
        schedule=config.backup.schedule,
        last_success_at=last_success_at,
        last_failure_at=None if failure is None else str(failure["finished_at"]),
        last_error=None if failure is None else str(failure["error"]),
        latest_archive=None if success is None else str(success["archive_path"]),
        latest_object_count=None if success is None else int(success["object_count"] or 0),
        time=config.backup.time,
        next_due_at=None
        if next_due is None
        else next_due.isoformat(timespec="microseconds"),
    )


def run_backup() -> ExportResult:
    config = load_config()
    if not config.backup.enabled or not config.backup.target:
        raise SafeVaultError("backup is not configured")
    target = Path(config.backup.target).expanduser().resolve(strict=False)
    _validate_current_backup_target(str(target))
    target.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    suffix = ".tar.gz" if config.backup.gzip else ".tar"
    archive_path = target / f"safevault-backup-{timestamp}{suffix}"
    job_id = _start_backup_job(target)
    try:
        result = export_vault(
            output=archive_path,
            gzip=config.backup.gzip,
            overwrite=False,
            skip_verify=config.backup.skip_verify,
        )
        if config.backup.overwrite_latest:
            latest = target / f"safevault-latest{suffix}"
            atomic_copy_file(result.output, latest)
        _finish_backup_job(job_id, "success", result.output, result.object_count, None)
        _prune_old_backups(target, keep_last=config.backup.keep_last)
        return result
    except Exception as exc:
        _finish_backup_job(job_id, "failed", archive_path, None, str(exc))
        raise


def run_due_backup(*, now: datetime | None = None) -> bool:
    config = load_config()
    if not config.backup.enabled or config.backup.schedule == "manual":
        return False
    status = get_backup_status()
    current = now or datetime.now(UTC)
    if _recent_failure_blocks_retry(status, current):
        return False
    last = _parse_iso(status.last_success_at) if status.last_success_at is not None else None
    next_due = next_due_after(last, config.backup.schedule, config.backup.time, current)
    if next_due is not None and current >= next_due:
        run_backup()
        return True
    return False


def next_due_after(
    last_success: datetime | None,
    schedule: str,
    time_of_day: str,
    now: datetime,
) -> datetime | None:
    if schedule == "manual":
        return None
    hour, minute = _parse_time_of_day(time_of_day)
    local_now = now.astimezone()
    due_today_local = local_now.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )
    due_today = due_today_local.astimezone(UTC)
    if last_success is None:
        return due_today
    last = last_success.astimezone(UTC)
    if schedule == "daily":
        if last >= due_today:
            return (due_today_local + timedelta(days=1)).astimezone(UTC)
        return due_today
    if schedule == "weekly":
        earliest_local = last.astimezone() + timedelta(days=7)
        candidate_local = earliest_local.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        if candidate_local < earliest_local:
            candidate_local += timedelta(days=1)
        if candidate_local < due_today_local:
            candidate_local = due_today_local
        return candidate_local.astimezone(UTC)
    raise SafeVaultError("backup schedule must be one of: manual, daily, weekly")


def _validate_current_backup_target(target: str | None) -> None:
    conn = connect()
    try:
        roots = [Path(root.path) for root in list_roots(conn)]
    finally:
        conn.close()
    validate_backup_target(target, protected_roots=roots)


def _recent_failure_blocks_retry(status: BackupStatus, now: datetime) -> bool:
    if status.last_failure_at is None:
        return False
    failure = _parse_iso(status.last_failure_at)
    if status.last_success_at is not None and _parse_iso(status.last_success_at) >= failure:
        return False
    return now - failure < BACKUP_FAILURE_RETRY_INTERVAL


def _parse_time_of_day(value: str) -> tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise SafeVaultError("backup time must use HH:MM")
    hour, minute = int(parts[0]), int(parts[1])
    if hour > 23 or minute > 59:
        raise SafeVaultError("backup time must use HH:MM")
    return hour, minute


def _start_backup_job(target: Path) -> int:
    conn = connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO backup_jobs(started_at, finished_at, status, target_path)
            VALUES (?, NULL, 'running', ?)
            """,
            (utc_now_iso(), str(target)),
        )
        conn.commit()
        assert cur.lastrowid is not None
        return int(cur.lastrowid)
    finally:
        conn.close()


def _finish_backup_job(
    job_id: int,
    status: str,
    archive_path: Path,
    object_count: int | None,
    error: str | None,
) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            UPDATE backup_jobs
            SET finished_at = ?, status = ?, archive_path = ?, object_count = ?, error = ?
            WHERE id = ?
            """,
            (utc_now_iso(), status, str(archive_path), object_count, error, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def _prune_old_backups(target: Path, *, keep_last: int) -> None:
    if keep_last <= 0:
        return
    backups = sorted(
        target.glob("safevault-backup-*.tar*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old in backups[keep_last:]:
        old.unlink(missing_ok=True)


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
