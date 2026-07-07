from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
import tarfile
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path, PurePosixPath

from safevault.atomic import fsync_dir
from safevault.errors import SafeVaultError
from safevault.hashing import hash_file
from safevault.object_store import is_valid_content_hash
from safevault.paths import ensure_home_layout, get_safevault_home, get_tmp_dir


@dataclass(frozen=True)
class ImportResult:
    archive: Path
    target_home: Path
    dry_run: bool
    object_count: int


@dataclass(frozen=True)
class ImportManifest:
    referenced_object_count: int
    exported_object_count: int


def import_vault(
    *,
    input_path: Path,
    target_home: Path,
    confirm: bool = False,
    overwrite: bool = False,
    skip_object_verify: bool = False,
) -> ImportResult:
    archive_path = input_path.expanduser().resolve(strict=False)
    raw_target = target_home.expanduser()
    if raw_target.is_symlink():
        raise SafeVaultError("target home must not be a symlink")
    target = raw_target.resolve(strict=False)
    current_home = get_safevault_home().resolve(strict=False)
    if target == current_home or target.is_relative_to(current_home):
        raise SafeVaultError("refusing to import into or inside current SAFEVAULT_HOME")
    if overwrite and (archive_path == target or archive_path.is_relative_to(target)):
        raise SafeVaultError("refusing to overwrite target containing the import archive")
    if target.exists() and not target.is_dir():
        raise SafeVaultError("target home exists and is not a directory")
    if target.exists() and any(target.iterdir()) and not overwrite:
        raise SafeVaultError("target home is not empty; pass --overwrite to replace it")

    members = _validated_members(archive_path)
    object_count = sum(1 for name in members if name.startswith("objects/"))

    if confirm:
        temp_parent = target.parent
        temp_parent.mkdir(parents=True, exist_ok=True)
    else:
        ensure_home_layout()
        temp_parent = get_tmp_dir()
    temp = temp_parent / f".{target.name}.import-{secrets.token_hex(8)}.tmp"
    if temp.is_symlink() or (temp.exists() and not temp.is_dir()):
        raise SafeVaultError("temporary import path is unsafe")
    moved = False
    try:
        temp.mkdir(parents=True)
        with tarfile.open(archive_path) as archive:
            for member in archive.getmembers():
                _validate_member_name(member.name)
                archive.extract(member, path=temp, filter="data")
        _validate_import_layout(temp, skip_object_verify=skip_object_verify)
        if not confirm:
            return ImportResult(
                archive=archive_path,
                target_home=target,
                dry_run=True,
                object_count=object_count,
            )
        if overwrite and target.exists():
            shutil.rmtree(target)
        elif target.exists():
            target.rmdir()
        os.replace(temp, target)
        moved = True
        fsync_dir(target.parent)
    finally:
        if not moved and temp.exists():
            shutil.rmtree(temp)
    return ImportResult(
        archive=archive_path,
        target_home=target,
        dry_run=False,
        object_count=object_count,
    )


def _validated_members(archive_path: Path) -> set[str]:
    if not archive_path.is_file():
        raise SafeVaultError(f"import archive not found: {archive_path}")
    try:
        with tarfile.open(archive_path) as archive:
            members = archive.getmembers()
    except tarfile.TarError as exc:
        raise SafeVaultError(f"invalid import archive: {archive_path}") from exc
    names: set[str] = set()
    for member in members:
        _validate_member_name(member.name)
        if member.name in names:
            raise SafeVaultError(f"duplicate archive member: {member.name}")
        if not member.isfile():
            raise SafeVaultError(f"unsupported archive member type: {member.name}")
        names.add(member.name)
    if "manifest.json" not in names:
        raise SafeVaultError("import archive missing manifest.json")
    if "vault.db" not in names:
        raise SafeVaultError("import archive missing vault.db")
    return names


def _validate_member_name(name: str) -> None:
    if "\\" in name:
        raise SafeVaultError(f"unsafe archive member path: {name}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise SafeVaultError(f"unsafe archive member path: {name}")
    if name in {"vault.db", "manifest.json"}:
        return
    parts = path.parts
    if (
        len(parts) == 4
        and parts[0] == "objects"
        and len(parts[1]) == 2
        and len(parts[2]) == 2
        and is_valid_content_hash(parts[3])
        and parts[1] == parts[3][:2]
        and parts[2] == parts[3][2:4]
    ):
        return
    raise SafeVaultError(f"unsupported archive member: {name}")


def _validate_import_layout(root: Path, *, skip_object_verify: bool) -> None:
    manifest = _validate_manifest(root / "manifest.json")
    db_path = root / "vault.db"
    conn = sqlite3.connect(db_path)
    try:
        result = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        if result.lower() != "ok":
            raise SafeVaultError(f"import database integrity check failed: {result}")
    except sqlite3.DatabaseError as exc:
        raise SafeVaultError("import database integrity check failed") from exc
    finally:
        conn.close()
    referenced_hashes = _referenced_hashes_from_db(db_path)
    if len(referenced_hashes) != manifest.referenced_object_count:
        raise SafeVaultError("import manifest referenced_object_count does not match database")
    objects_root = root / "objects"
    actual_object_hashes: set[str] = set()
    if objects_root.exists():
        for path in objects_root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            _validate_member_name(rel)
            content_hash = path.name
            actual_object_hashes.add(content_hash)
            if not skip_object_verify and hash_file(path) != content_hash:
                raise SafeVaultError(f"import object is corrupted: {content_hash}")
    if len(actual_object_hashes) != manifest.exported_object_count:
        raise SafeVaultError("import manifest exported_object_count does not match archive")
    missing = referenced_hashes - actual_object_hashes
    if missing:
        raise SafeVaultError(f"import archive missing referenced object: {sorted(missing)[0]}")
    extra = actual_object_hashes - referenced_hashes
    if extra:
        raise SafeVaultError(f"import archive includes unreferenced object: {sorted(extra)[0]}")


def _referenced_hashes_from_db(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT content_hash
            FROM versions
            WHERE content_hash IS NOT NULL
            """
        ).fetchall()
    except sqlite3.DatabaseError as exc:
        raise SafeVaultError("import database content hashes could not be read") from exc
    finally:
        conn.close()
    hashes: set[str] = set()
    for row in rows:
        content_hash = str(row[0])
        if not is_valid_content_hash(content_hash):
            raise SafeVaultError(f"import database references invalid content hash: {content_hash}")
        hashes.add(content_hash)
    return hashes


def _validate_manifest(path: Path) -> ImportManifest:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise SafeVaultError("import manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise SafeVaultError("import manifest must be a JSON object")
    if manifest.get("schema_version") != 1:
        raise SafeVaultError("unsupported import manifest schema")
    created_at = manifest.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        raise SafeVaultError("import manifest created_at must be a non-empty string")
    safevault_version = manifest.get("safevault_version")
    if not isinstance(safevault_version, str) or not safevault_version:
        raise SafeVaultError("import manifest safevault_version must be a non-empty string")
    if manifest.get("database") != "vault.db":
        raise SafeVaultError("unsupported import manifest database")
    if manifest.get("database_backup") is not True:
        raise SafeVaultError("import manifest must declare database_backup=true")
    referenced_object_count = _manifest_non_negative_int(
        manifest, "referenced_object_count"
    )
    exported_object_count = _manifest_non_negative_int(manifest, "exported_object_count")
    if manifest.get("included_orphans") is not False:
        raise SafeVaultError("import manifest included_orphans must be false")
    if manifest.get("compression") not in {"none", "gzip"}:
        raise SafeVaultError("import manifest compression must be 'none' or 'gzip'")
    return ImportManifest(
        referenced_object_count=referenced_object_count,
        exported_object_count=exported_object_count,
    )


def _manifest_non_negative_int(manifest: dict[str, object], field: str) -> int:
    value = manifest.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise SafeVaultError(f"import manifest {field} must be a non-negative integer")
    return value
