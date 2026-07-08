from __future__ import annotations

import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from safevault import __version__
from safevault.backup import configure_backup, get_backup_status, run_backup
from safevault.config import (
    BackupSchedule,
    load_config,
    save_config,
    validate_backup_target,
)
from safevault.daemon import get_daemon_status
from safevault.db import connect, list_roots
from safevault.doctor import DoctorResult, run_doctor
from safevault.durations import parse_duration
from safevault.errors import RootNotFoundError, SafeVaultError
from safevault.exporter import ExportResult, export_vault
from safevault.importer import ImportResult, import_vault
from safevault.models import ApplyResult, DiffResult
from safevault.object_store import iter_object_hashes, object_path
from safevault.paths import get_safevault_home, get_sandboxes_dir
from safevault.protection import (
    auto_detect_candidates,
    register_protected_root,
    validate_protection_path,
)
from safevault.prune import prune_unreferenced_objects
from safevault.recent import list_recent_deleted, list_recent_modified, search_files
from safevault.restore import restore_file
from safevault.retention import RetentionPlan, build_retention_plan
from safevault.sandbox import apply_sandbox, get_sandbox, list_sandboxes
from safevault.snapshot import create_snapshot
from safevault.ui.schemas import (
    DashboardStatus,
    DeletedEntry,
    RootDetail,
    RootSummary,
    SandboxSummary,
    VersionEntry,
)
from safevault.verify import VerifyResult, run_verify


def _object_store_size() -> int:
    total = 0
    for content_hash in iter_object_hashes():
        try:
            total += object_path(content_hash).stat().st_size
        except OSError:
            continue
    return total


def get_dashboard_status() -> DashboardStatus:
    doctor = run_doctor(deep=False)
    verify = run_verify(deep=False)
    conn = connect()
    try:
        roots_count = int(conn.execute("SELECT COUNT(*) FROM roots").fetchone()[0])
        snapshots_count = int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
        active_files_count = int(
            conn.execute("SELECT COUNT(*) FROM files WHERE status = 'active'").fetchone()[0]
        )
        deleted_files_count = int(
            conn.execute("SELECT COUNT(*) FROM files WHERE status = 'deleted'").fetchone()[0]
        )
        last_snapshot = conn.execute(
            """
            SELECT started_at
            FROM snapshots
            WHERE status = 'complete'
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        latest = conn.execute(
            "SELECT * FROM sandboxes ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    latest_sandbox = None
    if latest is not None:
        latest_sandbox = {
            "id": str(latest["id"]),
            "status": str(latest["status"]),
            "created_at": str(latest["created_at"]),
        }
    daemon = get_daemon_status()
    backup = get_backup_status()
    health_summary = "OK" if doctor.healthy and verify.healthy else "Warning"
    return DashboardStatus(
        version=__version__,
        safevault_home=str(get_safevault_home()),
        doctor_healthy=doctor.healthy,
        verify_healthy=verify.healthy,
        roots_count=roots_count,
        snapshots_count=snapshots_count,
        active_files_count=active_files_count,
        deleted_files_count=deleted_files_count,
        object_store_size=_object_store_size(),
        latest_sandbox=latest_sandbox,
        daemon_status=daemon.status,
        watched_roots=daemon.watched_roots,
        paused_roots=daemon.paused_roots,
        missing_roots=daemon.missing_roots,
        last_daemon_message=daemon.message,
        last_snapshot=None if last_snapshot is None else str(last_snapshot["started_at"]),
        last_backup=backup.last_success_at,
        next_backup_due=backup.next_due_at,
        health_summary=health_summary,
    )


def _root_summary_from_row(row) -> RootSummary:
    root_id = int(row["id"])
    active_count = int(row["active_count"] or 0)
    deleted_count = int(row["deleted_count"] or 0)
    return RootSummary(
        id=root_id,
        path=str(row["path"]),
        profile=str(row["profile"]),
        exists=Path(str(row["path"])).exists(),
        active_count=active_count,
        deleted_count=deleted_count,
        last_snapshot=(
            None if row["last_snapshot"] is None else str(row["last_snapshot"])
        ),
    )


def list_roots_for_ui() -> list[RootSummary]:
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT
              r.*,
              SUM(CASE WHEN f.status = 'active' THEN 1 ELSE 0 END) AS active_count,
              SUM(CASE WHEN f.status = 'deleted' THEN 1 ELSE 0 END) AS deleted_count,
              (
                SELECT MAX(s.started_at)
                FROM snapshots s
                WHERE s.root_id = r.id
              ) AS last_snapshot
            FROM roots r
            LEFT JOIN files f ON f.root_id = r.id
            GROUP BY r.id
            ORDER BY r.path
            """
        ).fetchall()
    finally:
        conn.close()
    return [_root_summary_from_row(row) for row in rows]


def add_root_from_ui(path: Path, profile: str) -> int:
    return register_protected_root(
        path,
        profile,
        source="ui",
        fail_if_exists=True,
    )


def should_show_onboarding() -> bool:
    return not load_config().app.onboarding_completed


def onboarding_candidates_for_ui() -> list[dict[str, object]]:
    return [
        {
            "path": candidate.path,
            "profile": candidate.profile,
            "recommended": candidate.recommended,
            "reason": candidate.reason,
        }
        for candidate in auto_detect_candidates()
    ]


def complete_onboarding_from_ui(
    *,
    roots: list[str],
    backup_target: str,
    backup_schedule: str,
    skip_roots: bool = False,
) -> dict[str, list[int]]:
    created_roots: list[int] = []
    snapshots: list[int] = []
    selected_roots = validate_onboarding_inputs(
        roots=roots,
        backup_target=backup_target,
        backup_schedule=backup_schedule,
        skip_roots=skip_roots,
    )
    candidate_profiles = {
        str(Path(candidate.path).resolve(strict=False)): candidate.profile
        for candidate in auto_detect_candidates()
    }
    for root_path in selected_roots:
        profile = candidate_profiles.get(str(root_path), "coding")
        try:
            root_id = add_root_from_ui(root_path, profile)
        except SafeVaultError as exc:
            if "already protected" not in str(exc):
                raise
            root_id = _root_id_for_path(root_path)
        created_roots.append(root_id)
        snapshots.append(create_snapshot(root_path, reason="onboarding-initial"))
    if backup_target.strip():
        configure_backup(Path(backup_target), _backup_schedule_for_ui(backup_schedule))
    config = load_config()
    save_config(replace(config, app=replace(config.app, onboarding_completed=True)))
    return {"roots": created_roots, "snapshots": snapshots}


def validate_onboarding_inputs(
    *,
    roots: list[str],
    backup_target: str,
    backup_schedule: str,
    skip_roots: bool = False,
) -> list[Path]:
    _backup_schedule_for_ui(backup_schedule)
    selected_roots = _dedupe_paths(
        validate_protection_path(Path(root_text)) for root_text in roots
    )
    if not selected_roots and not skip_roots:
        raise SafeVaultError("select at least one protected root or explicitly skip")
    if backup_target.strip():
        existing_roots = _existing_root_paths()
        validate_backup_target(
            backup_target,
            protected_roots=[*existing_roots, *selected_roots],
        )
    return selected_roots


def _dedupe_paths(paths) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _existing_root_paths() -> list[Path]:
    conn = connect()
    try:
        return [Path(root.path) for root in list_roots(conn)]
    finally:
        conn.close()


def backup_status_for_ui():
    return get_backup_status()


def run_backup_from_ui():
    return run_backup()


def _root_id_for_path(path: Path) -> int:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT id FROM roots WHERE path = ?",
            (str(path.expanduser().resolve(strict=False)),),
        ).fetchone()
        if row is None:
            raise RootNotFoundError(f"root not found: {path}")
        return int(row["id"])
    finally:
        conn.close()


def _backup_schedule_for_ui(value: str) -> BackupSchedule:
    if value not in {"manual", "daily", "weekly"}:
        raise SafeVaultError("backup schedule must be manual, daily, or weekly")
    return cast(BackupSchedule, value)


def _get_root_summary(root_id: int) -> RootSummary:
    roots = {root.id: root for root in list_roots_for_ui()}
    if root_id not in roots:
        raise RootNotFoundError(f"root not found: {root_id}")
    return roots[root_id]


def get_root_detail(root_id: int) -> RootDetail:
    root = _get_root_summary(root_id)
    conn = connect()
    try:
        snapshots = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, reason, started_at, finished_at, status
                FROM snapshots
                WHERE root_id = ?
                ORDER BY started_at DESC, id DESC
                LIMIT 20
                """,
                (root_id,),
            ).fetchall()
        ]
        deleted_markers = [
            dict(row)
            for row in conn.execute(
                """
                SELECT rel_path, captured_at
                FROM versions
                WHERE is_deleted_marker = 1
                  AND file_id IN (SELECT id FROM files WHERE root_id = ?)
                ORDER BY captured_at DESC
                LIMIT 20
                """,
                (root_id,),
            ).fetchall()
        ]
    finally:
        conn.close()
    return RootDetail(root=root, snapshots=snapshots, deleted_markers=deleted_markers)


def run_snapshot_for_root(root_id: int, reason: str = "ui-manual") -> int:
    root = _get_root_summary(root_id)
    return create_snapshot(Path(root.path), reason=reason)


def _find_root_row(root_id: int):
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM roots WHERE id = ?", (root_id,)).fetchone()
        if row is None:
            raise RootNotFoundError(f"root not found: {root_id}")
        return dict(row)
    finally:
        conn.close()


def plan_unprotect_from_ui(root_id: int) -> dict[str, object]:
    root = _find_root_row(root_id)
    conn = connect()
    try:
        files = int(
            conn.execute("SELECT COUNT(*) FROM files WHERE root_id = ?", (root_id,)).fetchone()[0]
        )
        versions = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM versions
                WHERE file_id IN (SELECT id FROM files WHERE root_id = ?)
                   OR snapshot_id IN (SELECT id FROM snapshots WHERE root_id = ?)
                """,
                (root_id, root_id),
            ).fetchone()[0]
        )
        snapshots = int(
            conn.execute(
                "SELECT COUNT(*) FROM snapshots WHERE root_id = ?", (root_id,)
            ).fetchone()[0]
        )
        events = int(
            conn.execute("SELECT COUNT(*) FROM events WHERE root_id = ?", (root_id,)).fetchone()[0]
        )
        sandboxes = int(
            conn.execute(
                "SELECT COUNT(*) FROM sandboxes WHERE root_id = ?", (root_id,)
            ).fetchone()[0]
        )
    finally:
        conn.close()
    return {
        "root_id": root_id,
        "root_path": root["path"],
        "files": files,
        "versions": versions,
        "snapshots": snapshots,
        "events": events,
        "sandboxes": sandboxes,
        "object_store_deleted": False,
    }


def unprotect_from_ui(root_id: int, confirmation: str) -> dict[str, object]:
    plan = plan_unprotect_from_ui(root_id)
    if confirmation not in {str(root_id), str(plan["root_path"])}:
        raise SafeVaultError("type the root id or root path to confirm unprotect")
    conn = connect()
    try:
        with conn:
            conn.execute("DELETE FROM change_batches WHERE root_id = ?", (root_id,))
            conn.execute("DELETE FROM protection_policies WHERE root_id = ?", (root_id,))
            conn.execute("DELETE FROM events WHERE root_id = ?", (root_id,))
            conn.execute(
                """
                DELETE FROM versions
                WHERE file_id IN (SELECT id FROM files WHERE root_id = ?)
                   OR snapshot_id IN (SELECT id FROM snapshots WHERE root_id = ?)
                """,
                (root_id, root_id),
            )
            conn.execute("DELETE FROM files WHERE root_id = ?", (root_id,))
            conn.execute("DELETE FROM snapshots WHERE root_id = ?", (root_id,))
            conn.execute("DELETE FROM sandboxes WHERE root_id = ?", (root_id,))
            conn.execute("DELETE FROM roots WHERE id = ?", (root_id,))
    finally:
        conn.close()
    return plan


def list_deleted_for_ui(since: str = "24h") -> list[DeletedEntry]:
    return [
        DeletedEntry(
            root_path=entry.root_path,
            rel_path=entry.rel_path,
            absolute_path=str(Path(entry.root_path) / entry.rel_path),
            detected_at=entry.detected_at,
        )
        for entry in list_recent_deleted(since=since)
    ]


def list_recent_modified_for_ui(since: str = "24h") -> list[dict[str, object]]:
    return [
        {
            "root_path": entry.root_path,
            "rel_path": entry.rel_path,
            "absolute_path": str(Path(entry.root_path) / entry.rel_path),
            "detected_at": entry.detected_at,
            "event_type": entry.event_type,
            "size": entry.size,
            "file_kind": entry.file_kind,
        }
        for entry in list_recent_modified(since=since, limit=20)
    ]


def search_for_ui(query: str, *, deleted: bool = False) -> list[dict[str, object]]:
    if not query.strip():
        return []
    return [
        {
            "root_path": entry.root_path,
            "rel_path": entry.rel_path,
            "absolute_path": str(Path(entry.root_path) / entry.rel_path),
            "status": entry.status,
            "file_kind": entry.file_kind,
            "size": entry.size,
            "last_seen_at": entry.last_seen_at,
        }
        for entry in search_files(query, deleted=deleted, limit=20)
    ]


def list_versions_for_file(path: Path) -> list[VersionEntry]:
    requested = path.expanduser().resolve(strict=False)
    conn = connect()
    try:
        roots = list_roots(conn)
        root = None
        for item in sorted(roots, key=lambda root_item: len(root_item.path), reverse=True):
            root_path = Path(item.path).resolve(strict=False)
            if requested == root_path or requested.is_relative_to(root_path):
                root = item
                break
        if root is None:
            raise RootNotFoundError("file is not under a protected root")
        rel_path = requested.relative_to(Path(root.path).resolve(strict=False)).as_posix()
        file_row = conn.execute(
            "SELECT * FROM files WHERE root_id = ? AND rel_path = ?",
            (root.id, rel_path),
        ).fetchone()
        if file_row is None:
            raise SafeVaultError(f"file has no tracked versions: {rel_path}")
        rows = conn.execute(
            """
            SELECT v.*, f.file_kind
            FROM versions v
            JOIN files f ON f.id = v.file_id
            WHERE v.file_id = ?
            ORDER BY v.id DESC
            """,
            (int(file_row["id"]),),
        ).fetchall()
    finally:
        conn.close()
    return [
        VersionEntry(
            version_id=int(row["id"]),
            captured_at=str(row["captured_at"]),
            size=None if row["size"] is None else int(row["size"]),
            content_hash=None if row["content_hash"] is None else str(row["content_hash"]),
            deleted=bool(int(row["is_deleted_marker"])),
            file_kind=str(row["file_kind"]),
        )
        for row in rows
    ]


def restore_from_ui(
    file: Path,
    *,
    latest: bool,
    version_id: int | None,
    to_path: Path | None,
    confirmation: str,
) -> Path:
    config = load_config()
    if config.app.advanced_mode:
        if confirmation != "RESTORE":
            raise SafeVaultError("type RESTORE to confirm restore")
    elif confirmation not in {"CONFIRM", "RESTORE"}:
        raise SafeVaultError("confirm restore action or type RESTORE to confirm restore")
    return restore_file(file, latest=latest, version_id=version_id, to_path=to_path)


def _sandbox_counts(sandbox_id: str) -> dict[str, int]:
    try:
        sandbox = get_sandbox(sandbox_id)
        diff_path = Path(sandbox.sandbox_path).parent / "diff.json"
        diff = DiffResult.from_dict(json.loads(diff_path.read_text(encoding="utf-8")))
        counts = diff.counts()
        return {
            "created": counts.get("created", 0),
            "modified": counts.get("modified", 0),
            "deleted": counts.get("deleted", 0),
        }
    except (OSError, SafeVaultError, json.JSONDecodeError):
        return {"created": 0, "modified": 0, "deleted": 0}


def list_sandboxes_for_ui() -> list[SandboxSummary]:
    return [
        SandboxSummary(
            id=sandbox.id,
            original_path=sandbox.original_path,
            sandbox_path=sandbox.sandbox_path,
            created_at=sandbox.created_at,
            status=sandbox.status,
            counts=_sandbox_counts(sandbox.id),
        )
        for sandbox in list_sandboxes()
    ]


def get_sandbox_diff(sandbox_id: str) -> tuple[SandboxSummary, DiffResult]:
    sandbox = get_sandbox(sandbox_id)
    diff_path = Path(sandbox.sandbox_path).parent / "diff.json"
    if not diff_path.is_file():
        raise SafeVaultError(f"diff file missing: {diff_path}")
    diff = DiffResult.from_dict(json.loads(diff_path.read_text(encoding="utf-8")))
    summary = SandboxSummary(
        id=sandbox.id,
        original_path=sandbox.original_path,
        sandbox_path=sandbox.sandbox_path,
        created_at=sandbox.created_at,
        status=sandbox.status,
        counts=diff.counts(),
    )
    return summary, diff


def apply_sandbox_from_ui(
    sandbox_id: str, *, allow_delete: bool, dry_run: bool, confirmation: str
) -> ApplyResult:
    if allow_delete and confirmation != "ALLOW DELETE":
        raise SafeVaultError("type ALLOW DELETE to apply deletions")
    return apply_sandbox(sandbox_id, allow_delete=allow_delete, dry_run=dry_run)


def run_doctor_for_ui(*, deep: bool) -> DoctorResult:
    return run_doctor(deep=deep)


def run_verify_for_ui(*, deep: bool) -> VerifyResult:
    return run_verify(deep=deep)


def prune_from_ui(*, dry_run: bool, confirmation: str = "") -> tuple[int, int]:
    if not dry_run and confirmation != "PRUNE":
        raise SafeVaultError("type PRUNE to confirm prune")
    return prune_unreferenced_objects(dry_run=dry_run)


def sandbox_clean_from_ui(
    *,
    dry_run: bool,
    confirm: bool,
    status: str = "applied",
    older_than: str = "30d",
    confirmation: str = "",
) -> dict[str, object]:
    if status != "applied":
        raise SafeVaultError("GUI sandbox-clean only supports status=applied")
    effective_dry_run = dry_run or not confirm
    if not effective_dry_run and confirmation != "CLEAN SANDBOXES":
        raise SafeVaultError("type CLEAN SANDBOXES to confirm sandbox cleanup")
    cutoff = datetime.now(UTC) - parse_duration(older_than)
    sandboxes_root = get_sandboxes_dir().resolve(strict=False)
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM sandboxes WHERE status = ? ORDER BY created_at",
            (status,),
        ).fetchall()
        selected = [
            row
            for row in rows
            if datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00")) < cutoff
        ]
        cleaned = 0
        skipped = 0
        for row in selected:
            sandbox_dir = Path(str(row["sandbox_path"])).parent.resolve(strict=False)
            if not (sandbox_dir != sandboxes_root and sandbox_dir.is_relative_to(sandboxes_root)):
                skipped += 1
                continue
            if sandbox_dir.exists() and (sandbox_dir.is_symlink() or not sandbox_dir.is_dir()):
                skipped += 1
                continue
            if not effective_dry_run:
                if sandbox_dir.exists():
                    shutil.rmtree(sandbox_dir)
                conn.execute("DELETE FROM sandboxes WHERE id = ?", (row["id"],))
            cleaned += 1
        if not effective_dry_run:
            conn.commit()
    finally:
        conn.close()
    return {
        "dry_run": effective_dry_run,
        "matched": len(selected),
        "cleaned": cleaned,
        "skipped": skipped,
    }


def retention_plan_for_ui(keep_days: int = 90) -> RetentionPlan:
    return build_retention_plan(keep_days=keep_days)


def export_from_ui(
    *,
    output: Path,
    gzip: bool,
    overwrite: bool,
    skip_verify: bool,
    allow_inside_vault: bool,
    overwrite_confirmation: str,
    skip_verify_confirmation: str,
) -> ExportResult:
    if overwrite and overwrite_confirmation != "OVERWRITE EXPORT":
        raise SafeVaultError("type OVERWRITE EXPORT to confirm export overwrite")
    if skip_verify and skip_verify_confirmation != "SKIP VERIFY":
        raise SafeVaultError("type SKIP VERIFY to confirm export without verification")
    return export_vault(
        output=output,
        gzip=gzip,
        overwrite=overwrite,
        skip_verify=skip_verify,
        allow_inside_vault=allow_inside_vault,
    )


def import_from_ui(
    *,
    input_path: Path,
    target_home: Path,
    dry_run: bool,
    confirm: bool,
    overwrite: bool,
    import_confirmation: str,
    overwrite_confirmation: str,
) -> ImportResult:
    if confirm and import_confirmation != "IMPORT":
        raise SafeVaultError("type IMPORT to confirm import")
    if overwrite and overwrite_confirmation != "OVERWRITE":
        raise SafeVaultError("type OVERWRITE to confirm overwrite")
    return import_vault(
        input_path=input_path,
        target_home=target_home,
        confirm=confirm and not dry_run,
        overwrite=overwrite,
    )
