from __future__ import annotations

import json
import os
import shutil
import sqlite3
import time
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from safevault.atomic import atomic_write_bytes, fsync_dir
from safevault.config import load_config, save_config
from safevault.db import backup_database_to, connect
from safevault.errors import SafeVaultError
from safevault.hashing import hash_file
from safevault.paths import (
    ensure_home_layout,
    get_default_safevault_home,
    get_objects_dir,
    get_safevault_home,
    get_storage_location_file,
    set_safevault_home_location,
)

GIB = 1024**3
MIGRATION_CONFIRMATION = "MOVE STORAGE"
_VOLATILE_HOME_FILES = {
    "daemon.lock",
    "daemon.stop",
    "vault.db",
    "vault.db-shm",
    "vault.db-wal",
}


@dataclass(frozen=True)
class RootStorageUsage:
    root_path: str
    minimum_bytes: int
    unique_objects: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LargeTrackedFile:
    root_path: str
    rel_path: str
    size: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StorageAnalysis:
    minimum_recoverable_bytes: int
    root_usage: list[RootStorageUsage]
    largest_files: list[LargeTrackedFile]

    def to_dict(self) -> dict[str, object]:
        return {
            "minimum_recoverable_bytes": self.minimum_recoverable_bytes,
            "root_usage": [item.to_dict() for item in self.root_usage],
            "largest_files": [item.to_dict() for item in self.largest_files],
        }


@dataclass(frozen=True)
class StorageStatus:
    home: str
    default_home: str
    location_file: str
    custom_location: bool
    object_store_bytes: int
    total_bytes: int
    free_bytes: int
    budget_gb: int
    over_budget: bool
    system_drive: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MigrationState:
    status: str
    source: str
    destination: str
    phase: str
    files_copied: int = 0
    bytes_copied: int = 0
    total_bytes: int = 0
    source_removed: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MigrationResult:
    source: str
    destination: str
    files_copied: int
    bytes_copied: int
    source_removed: bool
    cleanup_error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def get_storage_status() -> StorageStatus:
    ensure_home_layout()
    home = get_safevault_home()
    objects = get_objects_dir()
    object_bytes = _directory_size(objects)
    total_bytes = _directory_size(home)
    usage = shutil.disk_usage(home)
    budget_gb = load_config().retention.max_vault_size_gb
    system_drive = os.environ.get("SYSTEMDRIVE", "").casefold()
    return StorageStatus(
        home=str(home),
        default_home=str(get_default_safevault_home()),
        location_file=str(get_storage_location_file()),
        custom_location=home != get_default_safevault_home(),
        object_store_bytes=object_bytes,
        total_bytes=total_bytes,
        free_bytes=usage.free,
        budget_gb=budget_gb,
        over_budget=object_bytes > budget_gb * GIB,
        system_drive=bool(system_drive and home.drive.casefold() == system_drive),
    )


def analyze_storage(*, largest_limit: int = 20) -> StorageAnalysis:
    conn = connect()
    try:
        latest_rows = conn.execute(
            """
            SELECT
                r.path AS root_path,
                f.rel_path,
                v.content_hash,
                COALESCE(v.size, 0) AS size
            FROM files f
            JOIN roots r ON r.id = f.root_id
            JOIN versions v ON v.id = (
                SELECT latest.id
                FROM versions latest
                WHERE latest.file_id = f.id
                  AND latest.is_deleted_marker = 0
                ORDER BY latest.id DESC
                LIMIT 1
            )
            WHERE v.content_hash IS NOT NULL
            """
        ).fetchall()
    finally:
        conn.close()

    global_hashes: dict[str, int] = {}
    per_root: dict[str, dict[str, int]] = {}
    largest: list[LargeTrackedFile] = []
    for row in latest_rows:
        content_hash = str(row["content_hash"])
        size = int(row["size"])
        root_path = str(row["root_path"])
        global_hashes[content_hash] = max(global_hashes.get(content_hash, 0), size)
        hashes = per_root.setdefault(root_path, {})
        hashes[content_hash] = max(hashes.get(content_hash, 0), size)
        largest.append(
            LargeTrackedFile(
                root_path=root_path,
                rel_path=str(row["rel_path"]),
                size=size,
            )
        )
    root_usage = sorted(
        (
            RootStorageUsage(
                root_path=root_path,
                minimum_bytes=sum(hashes.values()),
                unique_objects=len(hashes),
            )
            for root_path, hashes in per_root.items()
        ),
        key=lambda item: item.minimum_bytes,
        reverse=True,
    )
    largest.sort(key=lambda item: item.size, reverse=True)
    return StorageAnalysis(
        minimum_recoverable_bytes=sum(global_hashes.values()),
        root_usage=root_usage,
        largest_files=largest[:largest_limit],
    )


def set_storage_budget(gigabytes: int) -> None:
    if gigabytes <= 0:
        raise SafeVaultError("storage budget must be positive")
    config = load_config()
    save_config(
        replace(
            config,
            retention=replace(config.retention, max_vault_size_gb=gigabytes),
        )
    )


def validate_storage_destination(
    destination: Path,
    *,
    additional_protected_roots: list[Path] | None = None,
) -> Path:
    source = get_safevault_home().resolve(strict=False)
    target = destination.expanduser().resolve(strict=False)
    if target.parent == target:
        raise SafeVaultError("storage destination must not be a filesystem root")
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise SafeVaultError("storage source and destination must not overlap")
    config = load_config()
    if config.backup.target:
        backup = Path(config.backup.target).resolve(strict=False)
        if target == backup or target.is_relative_to(backup) or backup.is_relative_to(target):
            raise SafeVaultError("storage destination must not overlap the backup target")
    roots = list(additional_protected_roots or [])
    conn = connect()
    try:
        roots.extend(
            Path(str(row["path"])).resolve(strict=False)
            for row in conn.execute("SELECT path FROM roots").fetchall()
        )
    finally:
        conn.close()
    for root in roots:
        if target == root or target.is_relative_to(root) or root.is_relative_to(target):
            raise SafeVaultError("storage destination must not overlap a protected root")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise SafeVaultError("storage destination must be an empty folder")
    return target


def migrate_storage(
    destination: Path,
    *,
    remove_source: bool = False,
    confirmation: str | None = None,
    stop_daemon: bool = False,
    restart_daemon: bool = False,
    deep_verify: bool = True,
) -> MigrationResult:
    if os.environ.get("SAFEVAULT_HOME"):
        raise SafeVaultError("storage migration is unavailable with SAFEVAULT_HOME set")
    if remove_source and confirmation != MIGRATION_CONFIRMATION:
        raise SafeVaultError(f"source removal requires confirmation: {MIGRATION_CONFIRMATION}")
    source = get_safevault_home().resolve(strict=False)
    target = validate_storage_destination(destination)
    state = MigrationState(
        status="running",
        source=str(source),
        destination=str(target),
        phase="preparing",
    )
    _write_migration_state(state)
    lock_path = _migration_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SafeVaultError("another storage migration is already running") from exc
    os.close(lock_fd)
    stage = target.with_name(f".{target.name}.safevault-migrating-{uuid.uuid4().hex}")
    was_running = False
    try:
        was_running = _ensure_daemon_stopped(stop_daemon)
        total_bytes = _copyable_size(source)
        database = source / "vault.db"
        if database.is_file():
            total_bytes += database.stat().st_size
        free_bytes = shutil.disk_usage(_existing_ancestor(target)).free
        required_bytes = total_bytes + GIB
        if free_bytes < required_bytes:
            raise SafeVaultError(
                "storage destination does not have enough free space; "
                f"required {required_bytes} bytes including safety reserve"
            )
        state = replace(state, phase="copying", total_bytes=total_bytes)
        _write_migration_state(state)
        stage.mkdir(parents=True)
        files_copied, bytes_copied = _copy_home(source, stage, state)
        if (source / "vault.db").is_file():
            backup_database_to(stage / "vault.db")
        state = replace(
            state,
            phase="verifying",
            files_copied=files_copied,
            bytes_copied=bytes_copied,
        )
        _write_migration_state(state)
        _verify_migrated_home(source, stage, deep=deep_verify)
        if target.exists():
            target.rmdir()
        os.replace(stage, target)
        fsync_dir(target.parent)
        set_safevault_home_location(target)
        cleanup_error = None
        source_removed = False
        if remove_source:
            try:
                shutil.rmtree(source)
                source_removed = True
            except OSError as exc:
                cleanup_error = str(exc)
        result = MigrationResult(
            source=str(source),
            destination=str(target),
            files_copied=files_copied,
            bytes_copied=bytes_copied,
            source_removed=source_removed,
            cleanup_error=cleanup_error,
        )
        _write_migration_state(
            MigrationState(
                status="complete",
                source=str(source),
                destination=str(target),
                phase="complete",
                files_copied=files_copied,
                bytes_copied=bytes_copied,
                total_bytes=total_bytes,
                source_removed=source_removed,
                error=cleanup_error,
            )
        )
        if restart_daemon and was_running:
            _restart_daemon()
        return result
    except Exception as exc:
        _write_migration_state(
            replace(state, status="failed", phase="failed", error=str(exc))
        )
        with suppress(OSError):
            if stage.exists():
                shutil.rmtree(stage)
        raise
    finally:
        lock_path.unlink(missing_ok=True)


def read_migration_state() -> MigrationState | None:
    path = _migration_state_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return MigrationState(**data)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def queue_migration_state(source: Path, destination: Path) -> None:
    _write_migration_state(
        MigrationState(
            status="queued",
            source=str(source),
            destination=str(destination),
            phase="queued",
        )
    )


def _directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _copyable_files(source: Path):
    for item in source.rglob("*"):
        if item.is_symlink():
            raise SafeVaultError(f"storage home contains unsupported symlink: {item}")
        if not item.is_file():
            continue
        rel = item.relative_to(source)
        if len(rel.parts) == 1 and rel.name in _VOLATILE_HOME_FILES:
            continue
        yield item, rel


def _copyable_size(source: Path) -> int:
    return sum(item.stat().st_size for item, _rel in _copyable_files(source))


def _existing_ancestor(path: Path) -> Path:
    current = path
    while not current.exists() and current.parent != current:
        current = current.parent
    if not current.exists():
        raise SafeVaultError("storage destination has no accessible parent")
    return current


def _copy_home(
    source: Path, stage: Path, initial_state: MigrationState
) -> tuple[int, int]:
    files_copied = 0
    bytes_copied = 0
    last_reported = 0
    for item, rel in _copyable_files(source):
        target = stage / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
        files_copied += 1
        bytes_copied += item.stat().st_size
        if files_copied % 100 == 0 or bytes_copied - last_reported >= 64 * 1024**2:
            _write_migration_state(
                replace(
                    initial_state,
                    files_copied=files_copied,
                    bytes_copied=bytes_copied,
                )
            )
            last_reported = bytes_copied
    return files_copied, bytes_copied


def _verify_migrated_home(source: Path, stage: Path, *, deep: bool) -> None:
    database = stage / "vault.db"
    if database.is_file():
        conn = sqlite3.connect(database)
        try:
            result = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            conn.close()
        if result.lower() != "ok":
            raise SafeVaultError(f"migrated database integrity check failed: {result}")
    source_objects = source / "objects"
    if not source_objects.exists():
        return
    for item in source_objects.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(source_objects)
        copied = stage / "objects" / rel
        if not copied.is_file() or copied.stat().st_size != item.stat().st_size:
            raise SafeVaultError(f"migrated object is missing or truncated: {rel}")
        if deep and len(item.name) == 64 and hash_file(copied) != item.name:
            raise SafeVaultError(f"migrated object failed hash verification: {rel}")


def _ensure_daemon_stopped(stop_daemon: bool) -> bool:
    from safevault.daemon import get_daemon_status, request_daemon_stop

    status = get_daemon_status()
    was_running = status.status in {"running", "stopping"} or status.lock_exists
    if not was_running:
        return False
    if not stop_daemon:
        raise SafeVaultError("stop background protection before migrating storage")
    request_daemon_stop()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = get_daemon_status()
        if status.status not in {"running", "stopping"} and not status.lock_exists:
            return True
        time.sleep(0.2)
    raise SafeVaultError("background protection did not stop within 60 seconds")


def _restart_daemon() -> None:
    from safevault.processes import spawn_safevault

    spawn_safevault(["daemon", "run"], log_name="daemon")


def _migration_state_path() -> Path:
    return get_storage_location_file().with_name(".safevault-migration.json")


def _migration_lock_path() -> Path:
    return get_storage_location_file().with_name(".safevault-migration.lock")


def _write_migration_state(state: MigrationState) -> None:
    path = _migration_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(path, json.dumps(state.to_dict(), indent=2).encode("utf-8"))
