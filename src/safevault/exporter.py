from __future__ import annotations

import io
import json
import os
import sqlite3
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from safevault import __version__
from safevault.atomic import fsync_dir
from safevault.db import backup_database_to
from safevault.errors import SafeVaultError
from safevault.hashing import hash_file
from safevault.object_store import is_valid_content_hash, object_path
from safevault.paths import ensure_home_layout, get_safevault_home, get_tmp_dir


@dataclass(frozen=True)
class ExportResult:
    output: Path
    object_count: int
    verified: bool
    database_backup: bool


def export_vault(
    *,
    output: Path,
    gzip: bool = False,
    allow_inside_vault: bool = False,
    overwrite: bool = False,
    skip_verify: bool = False,
) -> ExportResult:
    ensure_home_layout()
    output_path = output.expanduser().resolve(strict=False)
    vault_home = get_safevault_home().resolve(strict=False)
    if (
        not allow_inside_vault
        and (output_path == vault_home or output_path.is_relative_to(vault_home))
    ):
        raise SafeVaultError(
            "refusing to write export inside SAFEVAULT_HOME; pass --allow-inside-vault to override"
        )
    if output_path.exists() and not overwrite:
        raise SafeVaultError(f"export output already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f".{output_path.name}.tmp")
    db_backup = get_tmp_dir() / f".export-vault-{datetime.now(UTC).timestamp()}.db"
    object_hashes: list[str] = []
    try:
        backup_database_to(db_backup)
        object_hashes = sorted(referenced_hashes_from_backup(db_backup))
        validate_referenced_objects(object_hashes, deep=not skip_verify)
        with tarfile.open(tmp_path, "w:gz" if gzip else "w") as archive:
            archive.add(db_backup, arcname="vault.db")
            for content_hash in object_hashes:
                path = object_path(content_hash)
                if not path.is_file():
                    raise SafeVaultError(f"referenced object disappeared: {content_hash}")
                archive.add(
                    path,
                    arcname=(
                        f"objects/{content_hash[:2]}/"
                        f"{content_hash[2:4]}/{content_hash}"
                    ),
                )
            _add_manifest(
                archive,
                referenced_object_count=len(object_hashes),
                exported_object_count=len(object_hashes),
                verified=not skip_verify,
                compression="gzip" if gzip else "none",
            )
        os.replace(tmp_path, output_path)
        fsync_dir(output_path.parent)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        if db_backup.exists():
            db_backup.unlink(missing_ok=True)
    return ExportResult(
        output=output_path,
        object_count=len(object_hashes),
        verified=not skip_verify,
        database_backup=True,
    )


def referenced_hashes_from_backup(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT content_hash
            FROM versions
            WHERE content_hash IS NOT NULL
            """
        ).fetchall()
    finally:
        conn.close()
    hashes: set[str] = set()
    for row in rows:
        content_hash = str(row[0])
        if not is_valid_content_hash(content_hash):
            raise SafeVaultError(f"database backup references invalid content hash: {content_hash}")
        hashes.add(content_hash)
    return hashes


def validate_referenced_objects(content_hashes: set[str] | list[str], *, deep: bool) -> None:
    for content_hash in content_hashes:
        if not is_valid_content_hash(content_hash):
            raise SafeVaultError(f"invalid referenced content hash: {content_hash}")
        path = object_path(content_hash)
        if not path.is_file():
            raise SafeVaultError(f"referenced object is missing: {content_hash}")
        if deep and hash_file(path) != content_hash:
            raise SafeVaultError(f"referenced object is corrupted: {content_hash}")


def _add_manifest(
    archive: tarfile.TarFile,
    *,
    referenced_object_count: int,
    exported_object_count: int,
    verified: bool,
    compression: str,
) -> None:
    payload = json.dumps(
        {
            "schema_version": 1,
            "created_at": datetime.now(UTC).isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
            "safevault_version": __version__,
            "database": "vault.db",
            "database_backup": True,
            "referenced_object_count": referenced_object_count,
            "exported_object_count": exported_object_count,
            "included_orphans": False,
            "verified": verified,
            "compression": compression,
        },
        indent=2,
    ).encode("utf-8")
    info = tarfile.TarInfo("manifest.json")
    info.size = len(payload)
    info.mtime = int(datetime.now(UTC).timestamp())
    archive.addfile(info, io.BytesIO(payload))
