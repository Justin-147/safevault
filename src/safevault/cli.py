from __future__ import annotations

import json
import secrets
import shutil
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Annotated, cast

import typer
from rich.console import Console
from rich.table import Table

from safevault import __version__
from safevault.backup import (
    configure_backup,
    disable_backup,
    get_backup_status,
    run_backup,
)
from safevault.config import VALID_PROFILES, BackupSchedule
from safevault.daemon import (
    get_daemon_status,
    request_daemon_stop,
    run_daemon,
)
from safevault.db import (
    connect,
    find_containing_root,
    get_root_by_path,
    list_roots,
)
from safevault.doctor import run_doctor
from safevault.durations import parse_duration
from safevault.errors import FileNotTrackedError, RootNotFoundError, SafeVaultError
from safevault.exporter import export_vault
from safevault.importer import import_vault
from safevault.object_store import iter_object_hashes, object_path
from safevault.paths import ensure_home_layout, get_sandboxes_dir
from safevault.protection import (
    add_or_enable_protected_root,
    auto_detect_candidates,
    list_protection,
    pause_protected_root,
    register_protected_root,
    remove_protected_root,
    resume_protected_root,
    root_safety_issue,
)
from safevault.prune import prune_unreferenced_objects
from safevault.recent import (
    RecentEntry,
    SearchEntry,
    list_recent_activity,
    list_recent_deleted,
    list_recent_modified,
    search_files,
)
from safevault.restore import restore_file
from safevault.retention import build_retention_plan, build_smart_retention_plan
from safevault.sandbox import apply_sandbox, create_sandbox, list_sandboxes
from safevault.snapshot import create_snapshot, relative_path
from safevault.startup import install_user_startup, uninstall_user_startup
from safevault.storage import (
    MIGRATION_CONFIRMATION,
    analyze_storage,
    get_storage_status,
    migrate_storage,
    set_storage_budget,
)
from safevault.tray import run_tray
from safevault.verify import run_verify
from safevault.watcher import watch_roots

console = Console()
app = typer.Typer(no_args_is_help=True, invoke_without_command=True)
protect_app = typer.Typer(no_args_is_help=True)
recent_app = typer.Typer(no_args_is_help=True)
daemon_app = typer.Typer(no_args_is_help=True)
backup_app = typer.Typer(no_args_is_help=True)
storage_app = typer.Typer(no_args_is_help=True)

SAFE_SANDBOX_CLEAN_STATUSES = {"applied"}
LOCAL_UI_HOSTS = {"127.0.0.1", "localhost"}

app.add_typer(protect_app, name="protect")
app.add_typer(recent_app, name="recent")
app.add_typer(daemon_app, name="daemon")
app.add_typer(backup_app, name="backup")
app.add_typer(storage_app, name="storage")


def print_json(data: object) -> None:
    print(json.dumps(data, indent=2))


@dataclass(frozen=True)
class UnprotectPlan:
    root_id: int
    root_path: str
    files: int
    versions: int
    snapshots: int
    events: int
    sandboxes: int

    def to_dict(self) -> dict[str, object]:
        return {
            "root_id": self.root_id,
            "root_path": self.root_path,
            "files": self.files,
            "versions": self.versions,
            "snapshots": self.snapshots,
            "events": self.events,
            "sandboxes": self.sandboxes,
            "object_store_deleted": False,
        }


def handle_errors[F: Callable[..., object]](func: F) -> F:
    @wraps(func)
    def wrapper(*args: object, **kwargs: object) -> object:
        try:
            return func(*args, **kwargs)
        except SafeVaultError as exc:
            console.print(f"Error: {exc}", style="red", markup=False)
            raise typer.Exit(1) from None

    return wrapper  # type: ignore[return-value]


@app.callback()
def main_callback(version: bool = typer.Option(False, "--version")) -> None:
    if version:
        console.print(__version__)
        raise typer.Exit()


@app.command(name="init")
@handle_errors
def init_command(path: Path, profile: str = typer.Option("coding", "--profile")) -> None:
    if profile not in VALID_PROFILES:
        raise SafeVaultError("profile must be one of: " + ", ".join(sorted(VALID_PROFILES)))
    root = path.expanduser().resolve()
    if not root.exists():
        raise SafeVaultError(f"path does not exist: {root}")
    if not root.is_dir():
        raise SafeVaultError(f"path is not a directory: {root}")
    ensure_home_layout()
    root_id = register_protected_root(
        root,
        profile,
        source="init",
        fail_if_exists=False,
    )
    console.print(f"Initialized SafeVault root {root_id}: {root}")


@app.command()
@handle_errors
def snapshot(path: Path, reason: str = typer.Option("manual", "--reason")) -> None:
    snapshot_id = create_snapshot(path, reason=reason)
    console.print(f"Snapshot {snapshot_id} complete")


@app.command()
@handle_errors
def watch() -> None:
    watch_roots()


@app.command()
@handle_errors
def deleted(since: str = typer.Option("24h", "--since")) -> None:
    _print_recent_table(list_recent_deleted(since=since), include_event=False)


@recent_app.command(name="deleted")
@handle_errors
def recent_deleted(
    since: str = typer.Option("24h", "--since"),
    limit: int = typer.Option(100, "--limit", min=1),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    entries = list_recent_deleted(since=since, limit=limit)
    if json_output:
        print_json([_recent_to_dict(entry) for entry in entries])
        return
    _print_recent_table(entries, include_event=False)


@recent_app.command(name="modified")
@handle_errors
def recent_modified(
    since: str = typer.Option("24h", "--since"),
    limit: int = typer.Option(100, "--limit", min=1),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    entries = list_recent_modified(since=since, limit=limit)
    if json_output:
        print_json([_recent_to_dict(entry) for entry in entries])
        return
    _print_recent_table(entries, include_event=True)


@recent_app.command(name="activity")
@handle_errors
def recent_activity(
    since: str = typer.Option("24h", "--since"),
    limit: int = typer.Option(200, "--limit", min=1),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    entries = list_recent_activity(since=since, limit=limit)
    if json_output:
        print_json([_recent_to_dict(entry) for entry in entries])
        return
    _print_recent_table(entries, include_event=True)


@app.command(name="search")
@handle_errors
def search_command(
    query: str,
    deleted_only: bool = typer.Option(False, "--deleted"),
    root: Annotated[Path | None, typer.Option("--root")] = None,
    limit: int = typer.Option(100, "--limit", min=1),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    entries = search_files(query, deleted=deleted_only, root=root, limit=limit)
    if json_output:
        print_json([_search_to_dict(entry) for entry in entries])
        return
    table = Table("Root", "Path", "Status", "Kind", "Size", "Last Seen")
    for entry in entries:
        table.add_row(
            entry.root_path,
            entry.rel_path,
            entry.status,
            entry.file_kind,
            "" if entry.size is None else str(entry.size),
            entry.last_seen_at,
        )
    console.print(table)


@daemon_app.command(name="run")
@handle_errors
def daemon_run(
    test_once: Annotated[bool, typer.Option("--test-once", hidden=True)] = False,
    poll_interval: Annotated[float, typer.Option("--poll-interval", hidden=True)] = 1.0,
    force: bool = typer.Option(False, "--force"),
) -> None:
    console.print("Starting SafeVault daemon")
    run_daemon(test_once=test_once, poll_interval_seconds=poll_interval, force=force)
    if test_once:
        console.print("Daemon test run complete")


@daemon_app.command(name="status")
@handle_errors
def daemon_status(json_output: bool = typer.Option(False, "--json")) -> None:
    status = get_daemon_status()
    data = {
        "status": status.status,
        "pid": status.pid,
        "started_at": status.started_at,
        "last_heartbeat_at": status.last_heartbeat_at,
        "message": status.message,
        "lock_exists": status.lock_exists,
        "stop_requested": status.stop_requested,
        "protected_roots": status.protected_roots,
        "watched_roots": status.watched_roots,
        "paused_roots": status.paused_roots,
        "missing_roots": status.missing_roots,
    }
    if json_output:
        print_json(data)
        return
    table = Table("Field", "Value")
    for key, value in data.items():
        table.add_row(key.replace("_", " "), "" if value is None else str(value))
    console.print(table)


@daemon_app.command(name="stop")
@handle_errors
def daemon_stop() -> None:
    request_daemon_stop()
    console.print("SafeVault daemon stop requested")


@daemon_app.command(name="install")
@handle_errors
def daemon_install() -> None:
    result = install_user_startup(daemon=True, tray=False)
    console.print(f"Installed SafeVault daemon startup item: {result.daemon_entry}")


@daemon_app.command(name="uninstall")
@handle_errors
def daemon_uninstall() -> None:
    result = uninstall_user_startup(daemon=True, tray=False)
    if result.daemon_changed:
        console.print(f"Removed SafeVault daemon startup item: {result.daemon_entry}")
    else:
        console.print("SafeVault daemon startup item was not installed")


@backup_app.command(name="configure")
@handle_errors
def backup_configure(
    target: Annotated[Path, typer.Option("--target")],
    schedule: str = typer.Option("daily", "--schedule"),
    time: str = typer.Option("21:00", "--time"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    if schedule not in {"manual", "daily", "weekly"}:
        raise SafeVaultError("backup schedule must be one of: manual, daily, weekly")
    config = configure_backup(target, cast(BackupSchedule, schedule), time=time)
    data = {
        "enabled": config.backup.enabled,
        "target": config.backup.target,
        "schedule": config.backup.schedule,
        "time": config.backup.time,
    }
    if json_output:
        print_json(data)
        return
    console.print(f"Backup configured: {config.backup.target}")
    console.print(f"Schedule: {config.backup.schedule}")
    console.print(f"Time: {config.backup.time}")


@backup_app.command(name="status")
@handle_errors
def backup_status(json_output: bool = typer.Option(False, "--json")) -> None:
    status = get_backup_status()
    data = {
        "enabled": status.enabled,
        "target": status.target,
        "schedule": status.schedule,
        "last_success_at": status.last_success_at,
        "last_failure_at": status.last_failure_at,
        "last_error": status.last_error,
        "latest_archive": status.latest_archive,
        "latest_object_count": status.latest_object_count,
        "time": status.time,
        "next_due_at": status.next_due_at,
    }
    if json_output:
        print_json(data)
        return
    table = Table("Field", "Value")
    for key, value in data.items():
        table.add_row(key.replace("_", " "), "" if value is None else str(value))
    console.print(table)


@backup_app.command(name="run")
@handle_errors
def backup_run(json_output: bool = typer.Option(False, "--json")) -> None:
    result = run_backup()
    data = {
        "output": str(result.output),
        "objects": result.object_count,
        "verified": result.verified,
    }
    if json_output:
        print_json(data)
        return
    console.print(f"Backup archive: {result.output}")
    console.print(f"Objects exported: {result.object_count}")


@backup_app.command(name="disable")
@handle_errors
def backup_disable(json_output: bool = typer.Option(False, "--json")) -> None:
    config = disable_backup()
    data = {"enabled": config.backup.enabled}
    if json_output:
        print_json(data)
        return
    console.print("Automatic backup disabled")


@storage_app.command(name="status")
@handle_errors
def storage_status(json_output: bool = typer.Option(False, "--json")) -> None:
    status = get_storage_status()
    if json_output:
        print_json(status.to_dict())
        return
    table = Table("Field", "Value")
    table.add_row("Data location", status.home)
    table.add_row("Object store", _human_bytes(status.object_store_bytes))
    table.add_row("Total SafeVault data", _human_bytes(status.total_bytes))
    table.add_row("Free space", _human_bytes(status.free_bytes))
    table.add_row("Target budget", f"{status.budget_gb} GB")
    table.add_row("Over target", "yes" if status.over_budget else "no")
    table.add_row("On system drive", "yes" if status.system_drive else "no")
    console.print(table)


@storage_app.command(name="analyze")
@handle_errors
def storage_analyze(json_output: bool = typer.Option(False, "--json")) -> None:
    analysis = analyze_storage()
    if json_output:
        print_json(analysis.to_dict())
        return
    console.print(
        "Minimum space for one latest restorable version of every tracked file: "
        + _human_bytes(analysis.minimum_recoverable_bytes)
    )
    roots = Table("Protected root", "Minimum", "Unique objects")
    for root_item in analysis.root_usage:
        roots.add_row(
            root_item.root_path,
            _human_bytes(root_item.minimum_bytes),
            str(root_item.unique_objects),
        )
    console.print(roots)
    largest = Table("Protected root", "File", "Size")
    for file_item in analysis.largest_files:
        largest.add_row(
            file_item.root_path,
            file_item.rel_path,
            _human_bytes(file_item.size),
        )
    console.print(largest)


@storage_app.command(name="budget")
@handle_errors
def storage_budget(gigabytes: int) -> None:
    set_storage_budget(gigabytes)
    console.print(f"Storage target updated: {gigabytes} GB")


@storage_app.command(name="migrate")
@handle_errors
def storage_migrate(
    destination: Path,
    remove_source: bool = typer.Option(False, "--remove-source"),
    confirmation: str | None = typer.Option(None, "--confirm"),
    stop_daemon: bool = typer.Option(True, "--stop-daemon/--no-stop-daemon"),
    restart_daemon: bool = typer.Option(True, "--restart-daemon/--no-restart-daemon"),
    deep_verify: bool = typer.Option(True, "--deep-verify/--no-deep-verify"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    if remove_source and confirmation != MIGRATION_CONFIRMATION:
        raise SafeVaultError(
            f"--remove-source requires --confirm \"{MIGRATION_CONFIRMATION}\""
        )
    result = migrate_storage(
        destination,
        remove_source=remove_source,
        confirmation=confirmation,
        stop_daemon=stop_daemon,
        restart_daemon=restart_daemon,
        deep_verify=deep_verify,
    )
    if json_output:
        print_json(result.to_dict())
        return
    console.print(f"SafeVault data location: {result.destination}")
    console.print(f"Copied: {_human_bytes(result.bytes_copied)}")
    if result.source_removed:
        console.print(f"Old data removed: {result.source}")
    elif result.cleanup_error:
        console.print(f"Old data remains at {result.source}: {result.cleanup_error}")
    else:
        console.print(f"Verified old copy retained at: {result.source}")


@app.command()
@handle_errors
def versions(file: Path) -> None:
    conn = connect()
    try:
        requested = file.expanduser().resolve(strict=False)
        root = find_containing_root(conn, requested)
        if root is None:
            raise RootNotFoundError("file is not under a protected root")
        rel_path = relative_path(Path(root.path), requested)
        file_row = conn.execute(
            "SELECT * FROM files WHERE root_id = ? AND rel_path = ?", (root.id, rel_path)
        ).fetchone()
        if file_row is None:
            raise FileNotTrackedError(f"file has no tracked versions: {rel_path}")
        rows = conn.execute(
            """
            SELECT v.*, f.file_kind FROM versions v
            JOIN files f ON f.id = v.file_id
            WHERE v.file_id = ?
            ORDER BY v.id DESC
            """,
            (int(file_row["id"]),),
        ).fetchall()
        if not rows:
            raise FileNotTrackedError(f"file has no tracked versions: {rel_path}")
    finally:
        conn.close()

    table = Table("Version", "Timestamp", "Size", "Kind", "Hash", "Deleted")
    for row in rows:
        content_hash = row["content_hash"]
        table.add_row(
            str(row["id"]),
            str(row["captured_at"]),
            "" if row["size"] is None else str(row["size"]),
            str(row["file_kind"]),
            "" if content_hash is None else str(content_hash)[:12],
            "yes" if int(row["is_deleted_marker"]) else "no",
        )
    console.print(table)


@app.command()
@handle_errors
def restore(
    file: Path,
    latest: Annotated[bool, typer.Option("--latest")] = False,
    version: Annotated[int | None, typer.Option("--version")] = None,
    to: Annotated[Path | None, typer.Option("--to")] = None,
) -> None:
    target = restore_file(file, latest=latest, version_id=version, to_path=to)
    console.print(f"Restored to {target}")


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
@handle_errors
def run(
    ctx: typer.Context,
    project: Annotated[
        Path | None, typer.Option("--project", exists=False, file_okay=False)
    ] = None,
) -> None:
    if project is None:
        raise SafeVaultError("--project is required")
    command = list(ctx.args)
    sandbox_id, returncode, diff, diff_path = create_sandbox(project, command)
    counts = diff.counts()
    console.print(f"Sandbox id: {sandbox_id}")
    console.print(f"Command exit code: {returncode}")
    console.print(
        f"Diff: created={counts.get('created', 0)} "
        f"modified={counts.get('modified', 0)} deleted={counts.get('deleted', 0)}"
    )
    console.print(f"Diff file: {diff_path}")
    if returncode != 0:
        raise typer.Exit(returncode)


@app.command()
@handle_errors
def apply(
    sandbox_id: str,
    allow_delete: bool = typer.Option(False, "--allow-delete"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    result = apply_sandbox(sandbox_id, allow_delete=allow_delete, dry_run=dry_run)
    if dry_run:
        console.print("Dry run: no files changed")
        console.print(f"Would apply files: {result.applied}")
        console.print(f"Would delete files: {result.deleted}")
    else:
        console.print(f"Applied files: {result.applied}")
        console.print(f"Deleted files: {result.deleted}")
    if result.skipped_deletions:
        console.print("Skipped deletions:")
        for rel_path in result.skipped_deletions:
            console.print(f"- {rel_path}")
    if result.conflicts:
        console.print("Conflicts:")
        for rel_path in result.conflicts:
            console.print(f"- {rel_path}")
    if result.unsafe:
        console.print("Unsafe entries:")
        for rel_path in result.unsafe:
            console.print(f"- {rel_path}")
    if result.missing_sources:
        console.print("Missing sandbox sources:")
        for rel_path in result.missing_sources:
            console.print(f"- {rel_path}")
    if result.conflicts or result.unsafe or result.missing_sources:
        raise typer.Exit(2)


@app.command()
@handle_errors
def prune(
    keep_days: int = typer.Option(60, "--keep-days"),
    max_size: str = typer.Option("50GB", "--max-size"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    deleted_count, reclaimed = prune_unreferenced_objects(
        keep_days=keep_days, max_size=max_size, dry_run=dry_run
    )
    if json_output:
        print_json(
            {
                "dry_run": dry_run,
                "objects": deleted_count,
                "bytes": reclaimed,
            }
        )
        return
    if dry_run:
        console.print(f"Would delete objects: {deleted_count}")
        console.print(f"Would reclaim bytes: {reclaimed}")
    else:
        console.print(f"Deleted objects: {deleted_count}")
        console.print(f"Reclaimed bytes: {reclaimed}")


@app.command()
@handle_errors
def verify(
    deep: bool = typer.Option(False, "--deep"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    result = run_verify(deep=deep)
    if json_output:
        print_json(
            {
                "healthy": result.healthy,
                "deep": result.deep,
                "checked_objects": result.checked_objects,
                "missing_objects": result.missing_objects,
                "corrupted_objects": result.corrupted_objects,
                "invalid_references": result.invalid_references,
            }
        )
        if not result.healthy:
            raise typer.Exit(1)
        return
    mode = "deep" if deep else "fast"
    console.print(f"Verify mode: {mode}")
    console.print(f"Referenced objects checked: {result.checked_objects}")
    if result.missing_objects:
        console.print("Missing objects:")
        for content_hash in result.missing_objects:
            console.print(f"- {content_hash}")
    if result.corrupted_objects:
        console.print("Corrupted objects:")
        for content_hash in result.corrupted_objects:
            console.print(f"- {content_hash}")
    if result.invalid_references:
        console.print("Invalid references:")
        for content_hash in result.invalid_references:
            console.print(f"- {content_hash}")
    console.print("SafeVault verify healthy" if result.healthy else "SafeVault verify failed")
    if not result.healthy:
        raise typer.Exit(1)


@app.command()
@handle_errors
def doctor(
    json_output: bool = typer.Option(False, "--json"),
    deep: bool = typer.Option(False, "--deep"),
) -> None:
    result = run_doctor(deep=deep)
    if json_output:
        print_json(result.to_dict())
    else:
        if result.error_items:
            console.print("ERROR:")
            for item in result.error_items:
                console.print(f"- {item}")
        if result.warning_items:
            console.print("WARN:")
            for item in result.warning_items:
                console.print(f"- {item}")
        console.print("SafeVault healthy" if result.healthy else "SafeVault unhealthy")
    if not result.healthy:
        raise typer.Exit(1)


@app.command()
@handle_errors
def status(path: Path, json_output: bool = typer.Option(False, "--json")) -> None:
    conn = connect()
    try:
        requested = path.expanduser().resolve(strict=False)
        root = find_containing_root(conn, requested)
        if root is None:
            raise RootNotFoundError("path is not under a protected root")
        latest_snapshot = conn.execute(
            """
            SELECT * FROM snapshots
            WHERE root_id = ?
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """,
            (root.id,),
        ).fetchone()
        active_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM files WHERE root_id = ? AND status = 'active'",
                (root.id,),
            ).fetchone()[0]
        )
        deleted_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM files WHERE root_id = ? AND status = 'deleted'",
                (root.id,),
            ).fetchone()[0]
        )
        latest_sandbox = conn.execute(
            """
            SELECT * FROM sandboxes
            WHERE root_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (root.id,),
        ).fetchone()
    finally:
        conn.close()

    object_store_size = _object_store_size()
    doctor_result = run_doctor()
    health = (
        "healthy"
        if doctor_result.healthy
        else f"errors={len(doctor_result.error_items)} warnings={len(doctor_result.warning_items)}"
    )
    data = {
        "protected_root": root.path,
        "root_id": root.id,
        "last_snapshot": None if latest_snapshot is None else str(latest_snapshot["started_at"]),
        "tracked_active_files": active_count,
        "tracked_deleted_files": deleted_count,
        "object_store_size": object_store_size,
        "latest_sandbox": None
        if latest_sandbox is None
        else {
            "id": str(latest_sandbox["id"]),
            "status": str(latest_sandbox["status"]),
            "created_at": str(latest_sandbox["created_at"]),
        },
        "health": health,
    }
    if json_output:
        print_json(data)
        return
    table = Table("Field", "Value")
    table.add_row("Protected root", root.path)
    table.add_row("Root id", str(root.id))
    table.add_row(
        "Last snapshot",
        "" if latest_snapshot is None else str(latest_snapshot["started_at"]),
    )
    table.add_row("Tracked active files", str(active_count))
    table.add_row("Tracked deleted files", str(deleted_count))
    table.add_row("Object store size", str(object_store_size))
    table.add_row(
        "Latest sandbox",
        ""
        if latest_sandbox is None
        else f"{latest_sandbox['id']} ({latest_sandbox['status']})",
    )
    table.add_row("Health", health)
    console.print(table)


@app.command()
@handle_errors
def sandboxes(
    latest: bool = typer.Option(False, "--latest"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    rows = list_sandboxes(latest=latest)
    if json_output:
        print_json(
            [
                {
                    "id": row.id,
                    "root_id": row.root_id,
                    "original_path": row.original_path,
                    "sandbox_path": row.sandbox_path,
                    "created_at": row.created_at,
                    "status": row.status,
                }
                for row in rows
            ]
        )
        return
    table = Table("ID", "Original", "Created", "Status")
    for row in rows:
        table.add_row(row.id, row.original_path, row.created_at, row.status)
    console.print(table)


@app.command(name="roots")
@handle_errors
def roots_command(json_output: bool = typer.Option(False, "--json")) -> None:
    conn = connect()
    try:
        rows = list_roots(conn)
    finally:
        conn.close()
    data = [
        {
            "id": root.id,
            "path": root.path,
            "profile": root.profile,
            "created_at": root.created_at,
            "exists": Path(root.path).exists(),
        }
        for root in rows
    ]
    if json_output:
        print_json(data)
        return
    print("ID\tPath\tProfile\tCreated\tExists")
    for root in rows:
        print(
            f"{root.id}\t{root.path}\t{root.profile}\t{root.created_at}\t"
            f"{'yes' if Path(root.path).exists() else 'no'}"
        )


@protect_app.command(name="list")
@handle_errors
def protect_list(json_output: bool = typer.Option(False, "--json")) -> None:
    policies = list_protection()
    data = []
    for policy in policies:
        safety_issue = root_safety_issue(Path(policy.root_path))
        data.append(
            {
            "root_id": policy.root_id,
            "path": policy.root_path,
            "enabled": policy.enabled,
            "profile": policy.profile,
            "auto_snapshot": policy.auto_snapshot,
            "watch_enabled": policy.watch_enabled,
            "hourly_snapshot": policy.hourly_snapshot,
            "daily_snapshot": policy.daily_snapshot,
            "paused_until": policy.paused_until,
            "updated_at": policy.updated_at,
            "exists": Path(policy.root_path).exists(),
            "unsafe": safety_issue is not None,
            "safety_issue": safety_issue,
        }
        )
    if json_output:
        print_json(data)
        return
    table = Table(
        "Root ID",
        "Path",
        "Enabled",
        "Profile",
        "Watch",
        "Auto Snapshot",
        "Paused Until",
        "Unsafe",
        "Exists",
    )
    for item in data:
        table.add_row(
            str(item["root_id"]),
            str(item["path"]),
            "yes" if item["enabled"] else "no",
            str(item["profile"]),
            "yes" if item["watch_enabled"] else "no",
            "yes" if item["auto_snapshot"] else "no",
            "" if item["paused_until"] is None else str(item["paused_until"]),
            "" if not item["unsafe"] else str(item["safety_issue"]),
            "yes" if item["exists"] else "no",
        )
    console.print(table)


@protect_app.command(name="add")
@handle_errors
def protect_add(
    path: Path,
    profile: str = typer.Option("coding", "--profile"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    result = add_or_enable_protected_root(
        path,
        profile,
        source="protect-add",
        fail_if_exists=True,
    )
    data = {
        "root_id": result.root_id,
        "path": str(result.root_path),
        "profile": profile,
        "enabled": True,
        "reenabled": result.reenabled,
    }
    if json_output:
        print_json(data)
        return
    verb = "Re-enabled protected root" if result.reenabled else "Protected root"
    console.print(f"{verb} {result.root_id}: {data['path']}")


@protect_app.command(name="remove")
@handle_errors
def protect_remove(
    path: Path,
    confirm: bool = typer.Option(False, "--confirm"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    if not confirm:
        raise SafeVaultError(
            "protect remove disables automatic protection; pass --confirm to continue"
        )
    policy = remove_protected_root(path)
    data = {
        "root_id": policy.root_id,
        "path": policy.root_path,
        "enabled": False,
        "snapshots_preserved": True,
    }
    if json_output:
        print_json(data)
        return
    console.print(f"Disabled automatic protection for root {policy.root_id}: {policy.root_path}")
    console.print("Existing snapshots and object-store content were preserved")


@protect_app.command(name="pause")
@handle_errors
def protect_pause(
    path: Path,
    duration: str = typer.Option("30m", "--duration"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    policy = pause_protected_root(path, duration)
    data = {
        "root_id": policy.root_id,
        "path": policy.root_path,
        "paused": True,
        "duration": duration,
    }
    if json_output:
        print_json(data)
        return
    console.print(f"Paused automatic protection for root {policy.root_id}: {policy.root_path}")


@protect_app.command(name="resume")
@handle_errors
def protect_resume(
    path: Path,
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    policy = resume_protected_root(path)
    data = {
        "root_id": policy.root_id,
        "path": policy.root_path,
        "paused": False,
    }
    if json_output:
        print_json(data)
        return
    console.print(f"Resumed automatic protection for root {policy.root_id}: {policy.root_path}")


@protect_app.command(name="auto-detect")
@handle_errors
def protect_auto_detect(json_output: bool = typer.Option(False, "--json")) -> None:
    candidates = auto_detect_candidates()
    data = [
        {
            "path": candidate.path,
            "profile": candidate.profile,
            "recommended": candidate.recommended,
            "reason": candidate.reason,
        }
        for candidate in candidates
    ]
    if json_output:
        print_json(data)
        return
    table = Table("Path", "Profile", "Recommended", "Reason")
    for item in data:
        table.add_row(
            str(item["path"]),
            str(item["profile"]),
            "yes" if item["recommended"] else "no",
            str(item["reason"]),
        )
    console.print(table)


@app.command()
@handle_errors
def unprotect(
    path: Path,
    confirm: bool = typer.Option(False, "--confirm"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    requested = path.expanduser().resolve(strict=False)
    conn = connect()
    try:
        root = get_root_by_path(conn, requested)
        if root is None:
            raise RootNotFoundError("path is not a protected root")
        plan = _plan_unprotect(conn, root.id, root.path)
        if not confirm or dry_run:
            if json_output:
                print_json(plan.to_dict() | {"dry_run": True})
                if not dry_run and not confirm:
                    raise typer.Exit(1)
                return
            _print_unprotect_plan(plan)
            if not dry_run and not confirm:
                raise SafeVaultError("unprotect requires --confirm or --dry-run")
            return
        _execute_unprotect(conn, root.id)
    finally:
        conn.close()
    if json_output:
        print_json(plan.to_dict() | {"dry_run": False})
    else:
        console.print(f"Unprotected root {plan.root_id}: {plan.root_path}")


@app.command(name="sandbox-clean")
@handle_errors
def sandbox_clean(
    older_than: str = typer.Option("30d", "--older-than"),
    status: str = typer.Option("applied", "--status"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    confirm: bool = typer.Option(False, "--confirm"),
    include_non_applied: bool = typer.Option(False, "--include-non-applied"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    if status not in SAFE_SANDBOX_CLEAN_STATUSES and not include_non_applied:
        raise SafeVaultError(
            "sandbox-clean only cleans applied sandboxes by default; "
            "pass --include-non-applied for other statuses"
        )
    effective_dry_run = dry_run or not confirm
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
            if _parse_iso_datetime(str(row["created_at"])) < cutoff
        ]
        cleaned = 0
        skipped = 0
        for row in selected:
            sandbox_dir = Path(str(row["sandbox_path"])).parent.resolve(strict=False)
            if not (
                sandbox_dir != sandboxes_root
                and sandbox_dir.is_relative_to(sandboxes_root)
            ):
                skipped += 1
                continue
            if sandbox_dir.exists() and (
                sandbox_dir.is_symlink() or not sandbox_dir.is_dir()
            ):
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
    data = {
        "dry_run": effective_dry_run,
        "status": status,
        "older_than": older_than,
        "matched": len(selected),
        "cleaned": cleaned,
        "skipped": skipped,
    }
    if json_output:
        print_json(data)
        return
    if effective_dry_run and not dry_run:
        console.print("Dry run by default; pass --confirm to delete matching sandboxes")
    verb = "Would clean sandboxes" if effective_dry_run else "Cleaned sandboxes"
    console.print(f"{verb}: {cleaned}")
    if skipped:
        console.print(f"Skipped sandboxes: {skipped}")


@app.command()
@handle_errors
def export(
    output: Annotated[Path, typer.Option("--output")],
    gzip: bool = typer.Option(False, "--gzip"),
    allow_inside_vault: bool = typer.Option(False, "--allow-inside-vault"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    skip_verify: bool = typer.Option(False, "--skip-verify"),
) -> None:
    result = export_vault(
        output=output,
        gzip=gzip,
        allow_inside_vault=allow_inside_vault,
        overwrite=overwrite,
        skip_verify=skip_verify,
    )
    console.print(f"Exported vault: {result.output}")
    console.print(f"Objects exported: {result.object_count}")
    console.print(f"Verified before export: {'yes' if result.verified else 'no'}")


@app.command(name="import")
@handle_errors
def import_command(
    input_path: Annotated[Path, typer.Option("--input")],
    target_home: Annotated[Path, typer.Option("--target-home")],
    dry_run: bool = typer.Option(False, "--dry-run"),
    confirm: bool = typer.Option(False, "--confirm"),
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    result = import_vault(
        input_path=input_path,
        target_home=target_home,
        confirm=confirm and not dry_run,
        overwrite=overwrite,
    )
    if result.dry_run:
        console.print("Dry run: no files imported")
        console.print(f"Would import objects: {result.object_count}")
        console.print(f"Target home: {result.target_home}")
    else:
        console.print(f"Imported SafeVault home: {result.target_home}")
        console.print(f"Objects imported: {result.object_count}")


@app.command(name="tray")
@handle_errors
def tray_command(
    open_ui: bool = typer.Option(False, "--open-ui"),
    check: Annotated[bool, typer.Option("--check", hidden=True)] = False,
) -> None:
    run_tray(open_ui=open_ui, check=check)
    if check:
        console.print("SafeVault tray dependencies available")


@app.command(name="ui")
@handle_errors
def ui_command(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port", min=1, max=65535),
    open_browser: bool = typer.Option(False, "--open"),
    page: Annotated[str, typer.Option("--page", hidden=True)] = "home",
    allow_public_bind: bool = typer.Option(False, "--allow-public-bind"),
    test_token: Annotated[str | None, typer.Option("--test-token", hidden=True)] = None,
) -> None:
    if host not in LOCAL_UI_HOSTS and not allow_public_bind:
        raise SafeVaultError(
            "GUI binds only to 127.0.0.1/localhost by default; pass "
            "--allow-public-bind to bind another host"
        )
    try:
        import uvicorn

        from safevault.ui.app import create_app
        from safevault.ui.session import (
            clear_ui_session,
            create_ui_session,
            read_ui_session,
            ui_port_available,
            ui_session_reachable,
            ui_url,
            write_ui_session,
        )
    except ModuleNotFoundError as exc:
        if exc.name in {"fastapi", "uvicorn", "jinja2", "multipart"}:
            raise SafeVaultError("Install UI dependencies with: pip install -e '.[ui]'") from exc
        raise
    except RuntimeError as exc:
        if "python-multipart" in str(exc):
            raise SafeVaultError("Install UI dependencies with: pip install -e '.[ui]'") from exc
        raise

    start_paths = {"home": "/", "storage": "/storage"}
    try:
        start_path = start_paths[page]
    except KeyError as exc:
        raise SafeVaultError("UI page must be 'home' or 'storage'") from exc

    existing = read_ui_session()
    if existing is not None and ui_session_reachable(existing):
        url = ui_url(existing, path=start_path)
        console.print("SafeVault local UI is already running")
        console.print(url)
        if open_browser:
            webbrowser.open(url)
        return
    if not ui_port_available(host, port):
        raise SafeVaultError(
            f"SafeVault UI port {host}:{port} is already in use; "
            "use --port to choose another local port"
        )
    if existing is not None:
        clear_ui_session(existing)

    token = test_token or secrets.token_urlsafe(32)
    session = create_ui_session(host, port, token)
    write_ui_session(session)
    url = ui_url(session, path=start_path)
    console.print("SafeVault local UI")
    console.print("Local UI only. Not a remote admin console.")
    console.print(url)
    if open_browser:
        webbrowser.open(url)
    try:
        uvicorn.run(create_app(token=token), host=host, port=port)
    finally:
        clear_ui_session(session)


@app.command(name="retention-plan")
@handle_errors
def retention_plan(
    keep_days: int = typer.Option(90, "--keep-days"),
    smart: bool = typer.Option(False, "--smart"),
    verbose: bool = typer.Option(False, "--verbose"),
) -> None:
    result = build_smart_retention_plan() if smart else build_retention_plan(keep_days=keep_days)
    console.print(f"Candidate versions: {len(result.candidate_versions)}")
    console.print(f"Candidate snapshots: {len(result.candidate_snapshots)}")
    if verbose:
        for item in result.candidate_versions:
            console.print(f"- version {item.version_id}: {item.rel_path}")


def _recent_to_dict(entry: RecentEntry) -> dict[str, object]:
    return {
        "root_path": entry.root_path,
        "rel_path": entry.rel_path,
        "absolute_path": str(Path(entry.root_path) / entry.rel_path),
        "detected_at": entry.detected_at,
        "event_type": entry.event_type,
        "size": entry.size,
        "file_kind": entry.file_kind,
    }


def _search_to_dict(entry: SearchEntry) -> dict[str, object]:
    return {
        "root_path": entry.root_path,
        "rel_path": entry.rel_path,
        "absolute_path": str(Path(entry.root_path) / entry.rel_path),
        "status": entry.status,
        "file_kind": entry.file_kind,
        "size": entry.size,
        "last_seen_at": entry.last_seen_at,
    }


def _print_recent_table(entries: list[RecentEntry], *, include_event: bool) -> None:
    columns = ["Root", "Path"]
    if include_event:
        columns.append("Event")
    columns.extend(["Detected", "Size", "Kind"])
    table = Table(*columns)
    for entry in entries:
        values = [entry.root_path, entry.rel_path]
        if include_event:
            values.append(entry.event_type)
        values.extend(
            [
                entry.detected_at,
                "" if entry.size is None else str(entry.size),
                "" if entry.file_kind is None else entry.file_kind,
            ]
        )
        table.add_row(*values)
    console.print(table)


def _object_store_size() -> int:
    total = 0
    for content_hash in iter_object_hashes():
        path = object_path(content_hash)
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _plan_unprotect(conn, root_id: int, root_path: str) -> UnprotectPlan:
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
    sandboxes_count = int(
        conn.execute(
            "SELECT COUNT(*) FROM sandboxes WHERE root_id = ?", (root_id,)
        ).fetchone()[0]
    )
    return UnprotectPlan(
        root_id=root_id,
        root_path=root_path,
        files=files,
        versions=versions,
        snapshots=snapshots,
        events=events,
        sandboxes=sandboxes_count,
    )


def _execute_unprotect(conn, root_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM ai_change_sessions WHERE root_id = ?", (root_id,))
        conn.execute("DELETE FROM change_batches WHERE root_id = ?", (root_id,))
        conn.execute("DELETE FROM file_events WHERE root_id = ?", (root_id,))
        conn.execute("DELETE FROM version_timeline WHERE root_id = ?", (root_id,))
        conn.execute("DELETE FROM restore_points WHERE root_id = ?", (root_id,))
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


def _print_unprotect_plan(plan: UnprotectPlan) -> None:
    console.print(f"Root id: {plan.root_id}")
    console.print(f"Root path: {plan.root_path}")
    console.print(f"Files rows: {plan.files}")
    console.print(f"Version rows: {plan.versions}")
    console.print(f"Snapshot rows: {plan.snapshots}")
    console.print(f"Event rows: {plan.events}")
    console.print(f"Sandbox rows: {plan.sandboxes}")
    console.print("Object-store content files will not be deleted")


def _human_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def main() -> None:
    app()
