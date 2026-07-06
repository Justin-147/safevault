from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Annotated, TypeVar

import typer
from rich.console import Console
from rich.table import Table

from safevault.config import VALID_PROFILES
from safevault.db import connect, find_containing_root, get_or_create_root
from safevault.doctor import run_doctor
from safevault.durations import parse_duration
from safevault.errors import FileNotTrackedError, RootNotFoundError, SafeVaultError
from safevault.paths import ensure_home_layout
from safevault.prune import prune_unreferenced_objects
from safevault.restore import restore_file
from safevault.sandbox import apply_sandbox, create_sandbox, list_sandboxes
from safevault.snapshot import create_snapshot, relative_path
from safevault.watcher import watch_roots

console = Console()
app = typer.Typer(no_args_is_help=True)
F = TypeVar("F", bound=Callable[..., object])


def handle_errors(func: F) -> F:
    @wraps(func)
    def wrapper(*args: object, **kwargs: object) -> object:
        try:
            return func(*args, **kwargs)
        except SafeVaultError as exc:
            console.print(f"Error: {exc}", style="red")
            raise typer.Exit(1) from None

    return wrapper  # type: ignore[return-value]


@app.command(name="init")
@handle_errors
def init_command(path: Path, profile: str = typer.Option("coding", "--profile")) -> None:
    if profile not in VALID_PROFILES:
        raise SafeVaultError("profile must be one of: coding, documents")
    root = path.expanduser().resolve()
    if not root.exists():
        raise SafeVaultError(f"path does not exist: {root}")
    if not root.is_dir():
        raise SafeVaultError(f"path is not a directory: {root}")
    ensure_home_layout()
    conn = connect()
    try:
        root_id = get_or_create_root(conn, root, profile)
    finally:
        conn.close()
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
            UNION
            SELECT r.path AS root_path, e.rel_path AS rel_path, e.detected_at AS detected_at
            FROM events e
            JOIN roots r ON r.id = e.root_id
            WHERE e.event_type = 'deleted' AND e.detected_at >= ?
            ORDER BY detected_at DESC
            """,
            (cutoff, cutoff),
        ).fetchall()
    finally:
        conn.close()
    table = Table("Root", "Path", "Detected")
    for row in rows:
        table.add_row(str(row["root_path"]), str(row["rel_path"]), str(row["detected_at"]))
    console.print(table)


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
def apply(sandbox_id: str, allow_delete: bool = typer.Option(False, "--allow-delete")) -> None:
    applied, deleted_count, skipped = apply_sandbox(sandbox_id, allow_delete=allow_delete)
    console.print(f"Applied files: {applied}")
    console.print(f"Deleted files: {deleted_count}")
    if skipped:
        console.print("Skipped deletions:")
        for rel_path in skipped:
            console.print(f"- {rel_path}")


@app.command()
@handle_errors
def prune(
    keep_days: int = typer.Option(60, "--keep-days"),
    max_size: str = typer.Option("50GB", "--max-size"),
) -> None:
    deleted_count, reclaimed = prune_unreferenced_objects(keep_days=keep_days, max_size=max_size)
    console.print(f"Deleted objects: {deleted_count}")
    console.print(f"Reclaimed bytes: {reclaimed}")


@app.command()
@handle_errors
def doctor() -> None:
    result = run_doctor()
    if result.missing_tables:
        console.print("Missing tables/directories:")
        for item in result.missing_tables:
            console.print(f"- {item}")
    if result.missing_objects:
        console.print("Missing referenced objects:")
        for item in result.missing_objects:
            console.print(f"- {item}")
    if result.orphan_objects:
        console.print(f"Orphan objects: {len(result.orphan_objects)}")
    if result.temp_files:
        console.print(f"Temp or partial files: {len(result.temp_files)}")
    if result.missing_roots:
        console.print("Missing roots:")
        for item in result.missing_roots:
            console.print(f"- {item}")
    console.print("SafeVault healthy" if result.healthy else "SafeVault unhealthy")
    if not result.healthy:
        raise typer.Exit(1)


@app.command()
@handle_errors
def sandboxes(latest: bool = typer.Option(False, "--latest")) -> None:
    rows = list_sandboxes(latest=latest)
    table = Table("ID", "Original", "Created", "Status")
    for row in rows:
        table.add_row(row.id, row.original_path, row.created_at, row.status)
    console.print(table)


def main() -> None:
    app()
