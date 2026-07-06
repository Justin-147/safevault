from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from safevault.atomic import atomic_write_bytes
from safevault.config import PROTECTED_DELETE_NAMES
from safevault.db import connect, get_or_create_root, utc_now_iso
from safevault.diffing import diff_dirs
from safevault.errors import SafeVaultError, SandboxNotFoundError, UnsafeOperationError
from safevault.ignore import build_pathspec, is_ignored
from safevault.models import DiffEntry, DiffResult, SandboxRecord
from safevault.paths import ensure_home_layout, get_sandboxes_dir
from safevault.snapshot import create_snapshot, relative_path


def _sandbox_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"{stamp}-{secrets.token_hex(4)}"


def _copy_symlink(src: Path, dest: Path) -> None:
    target = os.readlink(src)
    try:
        os.symlink(target, dest, target_is_directory=src.is_dir())
    except (OSError, NotImplementedError):
        dest.write_bytes(f"SYMLINK\n{target}".encode("utf-8", "surrogateescape"))


def copy_project_to_sandbox(project: Path, sandbox_work: Path) -> None:
    project = project.expanduser().resolve()
    sandbox_work.mkdir(parents=True, exist_ok=True)
    spec = build_pathspec()
    stack = [project]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    src = Path(entry.path)
                    if is_ignored(project, src, spec):
                        continue
                    rel = relative_path(project, src)
                    dest = sandbox_work / Path(*PurePosixPath(rel).parts)
                    if entry.is_symlink():
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        _copy_symlink(src, dest)
                    elif entry.is_dir(follow_symlinks=False):
                        dest.mkdir(parents=True, exist_ok=True)
                        stack.append(src)
                    elif entry.is_file(follow_symlinks=False):
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest, follow_symlinks=False)
        except OSError:
            continue


def _insert_sandbox(
    sandbox_id: str, root_id: int, original_path: Path, sandbox_work: Path, status: str
) -> None:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO sandboxes(
                id, root_id, original_path, sandbox_path, created_at, status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (sandbox_id, root_id, str(original_path), str(sandbox_work), utc_now_iso(), status),
        )
        conn.commit()
    finally:
        conn.close()


def update_sandbox_status(sandbox_id: str, status: str) -> None:
    conn = connect()
    try:
        conn.execute("UPDATE sandboxes SET status = ? WHERE id = ?", (status, sandbox_id))
        conn.commit()
    finally:
        conn.close()


def create_sandbox(project: Path, command: list[str]) -> tuple[str, int, DiffResult, Path]:
    if not command:
        raise SafeVaultError("no command provided")
    project = project.expanduser().resolve()
    if not project.exists():
        raise SafeVaultError(f"project path does not exist: {project}")
    if not project.is_dir():
        raise SafeVaultError(f"project path is not a directory: {project}")

    ensure_home_layout()
    conn = connect()
    try:
        root_id = get_or_create_root(conn, project, "coding")
    finally:
        conn.close()

    create_snapshot(project, reason="pre-run")
    sandbox_id = _sandbox_id()
    sandbox_dir = get_sandboxes_dir() / sandbox_id
    sandbox_work = sandbox_dir / "work"
    copy_project_to_sandbox(project, sandbox_work)
    _insert_sandbox(sandbox_id, root_id, project, sandbox_work, "running")

    completed = subprocess.run(command, cwd=sandbox_work, check=False)
    diff = diff_dirs(project, sandbox_work)
    diff_path = sandbox_dir / "diff.json"
    atomic_write_bytes(diff_path, json.dumps(diff.to_dict(), indent=2).encode("utf-8"))
    update_sandbox_status(sandbox_id, "complete" if completed.returncode == 0 else "command_failed")
    return sandbox_id, completed.returncode, diff, diff_path


def _sandbox_from_row(row) -> SandboxRecord:
    return SandboxRecord(
        id=str(row["id"]),
        root_id=int(row["root_id"]),
        original_path=str(row["original_path"]),
        sandbox_path=str(row["sandbox_path"]),
        created_at=str(row["created_at"]),
        status=str(row["status"]),
    )


def get_sandbox(sandbox_id: str) -> SandboxRecord:
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM sandboxes WHERE id = ?", (sandbox_id,)).fetchone()
        if row is None:
            raise SandboxNotFoundError(f"sandbox not found: {sandbox_id}")
        return _sandbox_from_row(row)
    finally:
        conn.close()


def list_sandboxes(latest: bool = False) -> list[SandboxRecord]:
    conn = connect()
    try:
        sql = "SELECT * FROM sandboxes ORDER BY created_at DESC"
        if latest:
            sql += " LIMIT 1"
        return [_sandbox_from_row(row) for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def _load_diff(sandbox: SandboxRecord) -> DiffResult:
    diff_path = Path(sandbox.sandbox_path).parent / "diff.json"
    if not diff_path.is_file():
        raise SafeVaultError(f"diff file missing: {diff_path}")
    return DiffResult.from_dict(json.loads(diff_path.read_text(encoding="utf-8")))


def _safe_rel(rel_path: str) -> Path:
    rel = PurePosixPath(rel_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise UnsafeOperationError(f"unsafe relative path in diff: {rel_path}")
    return Path(*rel.parts)


def _inside_root(root: Path, path: Path) -> bool:
    root_resolved = root.resolve(strict=False)
    candidate = path.resolve(strict=False)
    return candidate == root_resolved or candidate.is_relative_to(root_resolved)


def _is_protected_delete(root: Path, entry: DiffEntry) -> bool:
    rel = PurePosixPath(entry.rel_path)
    return bool(rel.parts and rel.parts[0] in PROTECTED_DELETE_NAMES) or is_ignored(
        root, root / _safe_rel(entry.rel_path)
    )


def _copy_from_sandbox(source: Path, dest: Path) -> None:
    if source.is_symlink():
        target = os.readlink(source)
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        try:
            os.symlink(target, dest)
        except (OSError, NotImplementedError):
            atomic_write_bytes(dest, f"SYMLINK\n{target}".encode("utf-8", "surrogateescape"))
        return
    atomic_write_bytes(dest, source.read_bytes(), source.stat().st_mode & 0o777)


def apply_sandbox(sandbox_id: str, allow_delete: bool = False) -> tuple[int, int, list[str]]:
    sandbox = get_sandbox(sandbox_id)
    original = Path(sandbox.original_path)
    sandbox_work = Path(sandbox.sandbox_path)
    if not original.is_dir():
        raise SafeVaultError(f"original path no longer exists: {original}")
    if not sandbox_work.is_dir():
        raise SafeVaultError(f"sandbox work directory missing: {sandbox_work}")

    diff = _load_diff(sandbox)
    applied = 0
    deleted = 0
    skipped_deletions: list[str] = []
    try:
        create_snapshot(original, reason="pre-apply")
        for entry in diff.entries:
            rel = _safe_rel(entry.rel_path)
            dest = original / rel
            source = sandbox_work / rel
            if not _inside_root(original, dest):
                raise UnsafeOperationError(f"destination escapes original root: {entry.rel_path}")
            if entry.change_type in {"created", "modified"}:
                if not source.exists() and not source.is_symlink():
                    raise SafeVaultError(f"sandbox source missing: {source}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                _copy_from_sandbox(source, dest)
                applied += 1
            elif entry.change_type == "deleted":
                if not allow_delete:
                    skipped_deletions.append(entry.rel_path)
                    continue
                if _is_protected_delete(original, entry):
                    skipped_deletions.append(entry.rel_path)
                    continue
                if dest.is_file() or dest.is_symlink():
                    dest.unlink()
                    deleted += 1
                elif dest.is_dir():
                    try:
                        dest.rmdir()
                        deleted += 1
                    except OSError:
                        skipped_deletions.append(entry.rel_path)
                else:
                    skipped_deletions.append(entry.rel_path)
        update_sandbox_status(
            sandbox_id, "partially_applied" if skipped_deletions else "applied"
        )
        return applied, deleted, skipped_deletions
    except Exception:
        update_sandbox_status(sandbox_id, "failed")
        raise
