from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from safevault import __version__
from safevault.db import connect, get_or_create_root, list_roots
from safevault.doctor import DoctorResult, run_doctor
from safevault.durations import parse_duration
from safevault.errors import RootNotFoundError, SafeVaultError
from safevault.exporter import ExportResult, export_vault
from safevault.importer import ImportResult, import_vault
from safevault.models import ApplyResult, DiffResult
from safevault.object_store import iter_object_hashes, object_path
from safevault.paths import get_safevault_home, get_sandboxes_dir
from safevault.prune import prune_unreferenced_objects
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
    root = path.expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise SafeVaultError(f"path is not an existing directory: {root}")
    if profile not in {"coding", "documents"}:
        raise SafeVaultError("profile must be coding or documents")
    conn = connect()
    try:
        return get_or_create_root(conn, root, profile)
    finally:
        conn.close()


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
    duration = parse_duration(since)
    cutoff = (datetime.now(UTC) - duration).isoformat(timespec="microseconds")
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT r.path AS root_path, v.rel_path AS rel_path, v.captured_at AS detected_at
            FROM versions v
            JOIN files f ON f.id = v.file_id
            JOIN roots r ON r.id = f.root_id
            WHERE v.is_deleted_marker = 1 AND v.captured_at >= ?
            ORDER BY detected_at DESC
            """,
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()
    return [
        DeletedEntry(
            root_path=str(row["root_path"]),
            rel_path=str(row["rel_path"]),
            absolute_path=str(Path(str(row["root_path"])) / str(row["rel_path"])),
            detected_at=str(row["detected_at"]),
        )
        for row in rows
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
    if confirmation != "RESTORE":
        raise SafeVaultError("type RESTORE to confirm restore")
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
