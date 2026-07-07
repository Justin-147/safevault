from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from safevault.atomic import atomic_copy_file, atomic_write_bytes
from safevault.db import connect, get_or_create_root, utc_now_iso
from safevault.diffing import diff_dirs
from safevault.errors import SafeVaultError, SandboxNotFoundError, UnsafeOperationError
from safevault.filetypes import SafeFileKind, classify_no_follow
from safevault.hashing import hash_file, hash_path_no_follow, hash_symlink, symlink_payload
from safevault.ignore import build_pathspec, is_ignored
from safevault.models import ApplyResult, DiffEntry, DiffResult, SandboxRecord
from safevault.paths import ensure_home_layout, get_sandboxes_dir
from safevault.safety import (
    is_protected_rel_path,
    safe_rel_path,
    symlink_target_stays_within,
    validate_apply_target,
)
from safevault.snapshot import create_snapshot, relative_path
from safevault.symlinks import (
    external_symlink_placeholder,
    is_external_symlink_placeholder_file,
)

PLACEHOLDER_MAP_NAME = "placeholder-map.json"


def _sandbox_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    return f"{stamp}-{secrets.token_hex(4)}"


def _resolved_link_target(link_path: Path, link_target: str) -> Path:
    target = Path(link_target)
    if os.path.isabs(link_target):
        return target.resolve(strict=False)
    return (link_path.parent / link_target).resolve(strict=False)


def _copy_symlink(project: Path, sandbox_work: Path, src: Path, dest: Path) -> str | None:
    target = os.readlink(src)
    if not symlink_target_stays_within(project, src, target):
        atomic_write_bytes(dest, external_symlink_placeholder(target))
        return target

    resolved_target = _resolved_link_target(src, target)
    target_rel = resolved_target.relative_to(project)
    sandbox_target = sandbox_work / target_rel
    sandbox_link_target = os.path.relpath(sandbox_target, dest.parent)
    try:
        os.symlink(sandbox_link_target, dest, target_is_directory=src.is_dir())
    except (OSError, NotImplementedError):
        atomic_write_bytes(dest, symlink_payload(sandbox_link_target))
    return None


def copy_project_to_sandbox(project: Path, sandbox_work: Path) -> dict[str, str]:
    project = project.expanduser().resolve()
    sandbox_work.mkdir(parents=True, exist_ok=True)
    placeholder_map: dict[str, str] = {}
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
                        external_target = _copy_symlink(project, sandbox_work, src, dest)
                        if external_target is not None:
                            placeholder_map[rel] = external_target
                    elif entry.is_dir(follow_symlinks=False):
                        dest.mkdir(parents=True, exist_ok=True)
                        stack.append(src)
                    elif entry.is_file(follow_symlinks=False):
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest, follow_symlinks=False)
        except OSError:
            continue
    return placeholder_map


def _write_placeholder_map(sandbox_dir: Path, placeholder_map: dict[str, str]) -> Path:
    payload = {
        "schema_version": 1,
        "external_symlink_placeholders": placeholder_map,
    }
    path = sandbox_dir / PLACEHOLDER_MAP_NAME
    atomic_write_bytes(path, json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))
    return path


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
    placeholder_map = copy_project_to_sandbox(project, sandbox_work)
    _write_placeholder_map(sandbox_dir, placeholder_map)
    _insert_sandbox(sandbox_id, root_id, project, sandbox_work, "running")

    completed = subprocess.run(command, cwd=sandbox_work, check=False)
    diff = diff_dirs(
        project, sandbox_work, candidate_placeholder_map=placeholder_map
    )
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
    diff = DiffResult.from_dict(json.loads(diff_path.read_text(encoding="utf-8")))
    if diff.original_root is not None and Path(diff.original_root).resolve(strict=False) != Path(
        sandbox.original_path
    ).resolve(strict=False):
        raise SafeVaultError("diff original_root does not match sandbox metadata")
    if diff.sandbox_root is not None and Path(diff.sandbox_root).resolve(strict=False) != Path(
        sandbox.sandbox_path
    ).resolve(strict=False):
        raise SafeVaultError("diff sandbox_root does not match sandbox metadata")
    return diff


def _copy_from_sandbox(original: Path, source: Path, dest: Path) -> None:
    if source.is_symlink():
        target = os.readlink(source)
        if not symlink_target_stays_within(original, dest, target):
            raise UnsafeOperationError(f"refusing to apply external symlink: {dest}")
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        try:
            os.symlink(target, dest)
        except (OSError, NotImplementedError):
            atomic_write_bytes(dest, symlink_payload(target))
        return
    atomic_copy_file(source, dest, source.stat().st_mode & 0o777)


def _entry_source_hash(source: Path) -> str:
    if source.is_symlink():
        return hash_symlink(source)
    return hash_file(source)


def _validate_diff_entry(entry: DiffEntry) -> None:
    if entry.change_type not in {"created", "modified", "deleted"}:
        raise UnsafeOperationError(f"unknown change type: {entry.change_type}")
    if entry.file_kind not in {"file", "symlink", "external_symlink_placeholder"}:
        raise UnsafeOperationError(f"unknown file kind: {entry.file_kind}")
    if entry.old_file_kind is not None and entry.old_file_kind not in {
        "file",
        "symlink",
        "external_symlink_placeholder",
    }:
        raise UnsafeOperationError(f"unknown old file kind: {entry.old_file_kind}")
    if entry.file_kind == "external_symlink_placeholder":
        raise UnsafeOperationError("external symlink placeholder cannot be applied")
    if entry.change_type == "created" and entry.new_hash is None:
        raise UnsafeOperationError("created entry missing new_hash")
    if entry.change_type == "modified" and (
        entry.old_hash is None or entry.new_hash is None
    ):
        raise UnsafeOperationError("modified entry missing old_hash or new_hash")
    if entry.change_type == "deleted" and entry.old_hash is None:
        raise UnsafeOperationError("deleted entry missing old_hash")
    if is_protected_rel_path(entry.rel_path):
        raise UnsafeOperationError(f"protected or ignored path in diff: {entry.rel_path}")
    safe_rel_path(entry.rel_path)


def apply_sandbox(
    sandbox_id: str, allow_delete: bool = False, dry_run: bool = False
) -> ApplyResult:
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
    conflicts: list[str] = []
    unsafe: list[str] = []
    missing_sources: list[str] = []
    try:
        if not dry_run:
            create_snapshot(original, reason="pre-apply")
        for entry in diff.entries:
            try:
                _validate_diff_entry(entry)
                dest = validate_apply_target(original, entry.rel_path)
                rel = safe_rel_path(entry.rel_path)
                source = sandbox_work / rel
            except UnsafeOperationError as exc:
                unsafe.append(f"{entry.rel_path}: {exc}")
                continue

            if entry.change_type in {"created", "modified"}:
                if not source.exists() and not source.is_symlink():
                    missing_sources.append(entry.rel_path)
                    continue
                source_kind = classify_no_follow(source)
                if source_kind == SafeFileKind.DIRECTORY:
                    unsafe.append(f"{entry.rel_path}: sandbox source is a directory")
                    continue
                if source_kind == SafeFileKind.OTHER:
                    unsafe.append(
                        f"{entry.rel_path}: sandbox source is not a regular file or symlink"
                    )
                    continue
                expected_source_kind = (
                    SafeFileKind.REGULAR
                    if entry.file_kind == "file"
                    else SafeFileKind.SYMLINK
                )
                if source_kind != expected_source_kind:
                    unsafe.append(f"{entry.rel_path}: sandbox source kind mismatch")
                    continue
                is_placeholder, _placeholder_target = is_external_symlink_placeholder_file(
                    source
                )
                if is_placeholder:
                    unsafe.append(
                        f"{entry.rel_path}: external symlink placeholder cannot be applied"
                    )
                    continue
                if source.is_symlink() and not symlink_target_stays_within(
                    original, dest, os.readlink(source)
                ):
                    unsafe.append(f"{entry.rel_path}: external symlink target")
                    continue
                if _entry_source_hash(source) != entry.new_hash:
                    unsafe.append(f"{entry.rel_path}: sandbox source hash mismatch")
                    continue

                if entry.change_type == "created" and (dest.exists() or dest.is_symlink()):
                    conflicts.append(entry.rel_path)
                    continue
                if entry.change_type == "modified":
                    if not dest.exists() and not dest.is_symlink():
                        conflicts.append(entry.rel_path)
                        continue
                    if (
                        entry.old_file_kind is not None
                        and entry.old_file_kind != entry.file_kind
                    ):
                        unsafe.append(
                            f"{entry.rel_path}: changing file kind from "
                            f"{entry.old_file_kind} to {entry.file_kind} is not auto-applied"
                        )
                        continue
                    dest_kind = classify_no_follow(dest)
                    expected_dest_kind = (
                        SafeFileKind.REGULAR
                        if (entry.old_file_kind or entry.file_kind) == "file"
                        else SafeFileKind.SYMLINK
                    )
                    if dest_kind != expected_dest_kind:
                        conflicts.append(entry.rel_path)
                        continue
                    if hash_path_no_follow(dest) != entry.old_hash:
                        conflicts.append(entry.rel_path)
                        continue

                if not dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    _copy_from_sandbox(original, source, dest)
                applied += 1
            elif entry.change_type == "deleted":
                if not allow_delete:
                    skipped_deletions.append(entry.rel_path)
                    continue
                if not dest.exists() and not dest.is_symlink():
                    skipped_deletions.append(entry.rel_path)
                    continue
                dest_kind = classify_no_follow(dest)
                expected_dest_kind = (
                    SafeFileKind.REGULAR
                    if entry.file_kind == "file"
                    else SafeFileKind.SYMLINK
                )
                if dest_kind == SafeFileKind.DIRECTORY:
                    unsafe.append(f"{entry.rel_path}: refusing to delete directory")
                    continue
                if dest_kind == SafeFileKind.OTHER:
                    unsafe.append(f"{entry.rel_path}: refusing to delete special file")
                    continue
                if dest_kind != expected_dest_kind:
                    conflicts.append(entry.rel_path)
                    continue
                if hash_path_no_follow(dest) != entry.old_hash:
                    conflicts.append(entry.rel_path)
                    continue
                if not dry_run:
                    dest.unlink()
                deleted += 1

        result = ApplyResult(
            applied=applied,
            deleted=deleted,
            skipped_deletions=skipped_deletions,
            conflicts=conflicts,
            unsafe=unsafe,
            missing_sources=missing_sources,
        )
        if not dry_run:
            if applied or deleted:
                create_snapshot(original, reason="post-apply")
            status = "partially_applied" if result.has_skips else "applied"
            update_sandbox_status(sandbox_id, status)
        return result
    except Exception:
        if not dry_run:
            update_sandbox_status(sandbox_id, "failed")
        raise
