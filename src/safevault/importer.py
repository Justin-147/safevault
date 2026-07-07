from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tarfile
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path, PurePosixPath

from safevault.errors import SafeVaultError
from safevault.hashing import hash_file
from safevault.object_store import is_valid_content_hash
from safevault.paths import get_safevault_home


@dataclass(frozen=True)
class ImportResult:
    archive: Path
    target_home: Path
    dry_run: bool
    object_count: int


def import_vault(
    *,
    input_path: Path,
    target_home: Path,
    confirm: bool = False,
    overwrite: bool = False,
    skip_object_verify: bool = False,
) -> ImportResult:
    archive_path = input_path.expanduser().resolve(strict=False)
    target = target_home.expanduser().resolve(strict=False)
    current_home = get_safevault_home().resolve(strict=False)
    if target == current_home and not (confirm and overwrite):
        raise SafeVaultError(
            "refusing to import into current SAFEVAULT_HOME without --confirm --overwrite"
        )
    if target.exists() and not target.is_dir():
        raise SafeVaultError("target home exists and is not a directory")
    if target.exists() and any(target.iterdir()) and not overwrite:
        raise SafeVaultError("target home is not empty; pass --overwrite to replace it")

    members = _validated_members(archive_path)
    object_count = sum(1 for name in members if name.startswith("objects/"))
    if not confirm:
        return ImportResult(
            archive=archive_path,
            target_home=target,
            dry_run=True,
            object_count=object_count,
        )

    temp_parent = target.parent
    temp_parent.mkdir(parents=True, exist_ok=True)
    temp = temp_parent / f".{target.name}.import-tmp"
    if temp.exists():
        shutil.rmtree(temp)
    try:
        temp.mkdir(parents=True)
        with tarfile.open(archive_path) as archive:
            for member in archive.getmembers():
                _validate_member_name(member.name)
                archive.extract(member, path=temp, filter="data")
        _validate_import_layout(temp, skip_object_verify=skip_object_verify)
        if overwrite and target.exists():
            shutil.rmtree(target)
        elif target.exists():
            target.rmdir()
        os.replace(temp, target)
    finally:
        if temp.exists():
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
    expected_object_count = _validate_manifest(root / "manifest.json")
    db_path = root / "vault.db"
    conn = sqlite3.connect(db_path)
    try:
        result = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        if result.lower() != "ok":
            raise SafeVaultError(f"import database integrity check failed: {result}")
    finally:
        conn.close()
    objects_root = root / "objects"
    actual_object_count = 0
    if not objects_root.exists():
        if expected_object_count != 0:
            raise SafeVaultError("import manifest object_count does not match archive")
        return
    for path in objects_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        _validate_member_name(rel)
        actual_object_count += 1
        content_hash = path.name
        if not skip_object_verify and hash_file(path) != content_hash:
            raise SafeVaultError(f"import object is corrupted: {content_hash}")
    if actual_object_count != expected_object_count:
        raise SafeVaultError("import manifest object_count does not match archive")


def _validate_manifest(path: Path) -> int:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise SafeVaultError("import manifest is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise SafeVaultError("import manifest must be a JSON object")
    if manifest.get("schema_version") != 1:
        raise SafeVaultError("unsupported import manifest schema")
    if manifest.get("database") != "vault.db":
        raise SafeVaultError("unsupported import manifest database")
    if manifest.get("database_backup") is not True:
        raise SafeVaultError("import manifest must declare database_backup=true")
    object_count = manifest.get("object_count")
    if (
        not isinstance(object_count, int)
        or isinstance(object_count, bool)
        or object_count < 0
    ):
        raise SafeVaultError("import manifest object_count must be a non-negative integer")
    return object_count
