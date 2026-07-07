from __future__ import annotations

import io
import json
import os
import tarfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from safevault import __version__
from safevault.atomic import fsync_dir
from safevault.db import backup_database_to
from safevault.errors import SafeVaultError
from safevault.object_store import iter_object_hashes, object_path
from safevault.paths import ensure_home_layout, get_safevault_home, get_tmp_dir
from safevault.verify import run_verify


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
    if not skip_verify:
        verify_result = run_verify(deep=True)
        if not verify_result.healthy:
            raise SafeVaultError(
                "refusing to export unhealthy vault; run safevault verify --deep for details "
                "or pass --skip-verify"
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f".{output_path.name}.tmp")
    db_backup = get_tmp_dir() / f".export-vault-{datetime.now(UTC).timestamp()}.db"
    object_hashes = sorted(iter_object_hashes())
    try:
        backup_database_to(db_backup)
        with tarfile.open(tmp_path, "w:gz" if gzip else "w") as archive:
            archive.add(db_backup, arcname="vault.db")
            for content_hash in object_hashes:
                path = object_path(content_hash)
                if path.is_file():
                    archive.add(
                        path,
                        arcname=(
                            f"objects/{content_hash[:2]}/"
                            f"{content_hash[2:4]}/{content_hash}"
                        ),
                    )
            _add_manifest(
                archive,
                object_count=len(object_hashes),
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


def _add_manifest(
    archive: tarfile.TarFile, *, object_count: int, verified: bool, compression: str
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
            "object_count": object_count,
            "verified": verified,
            "compression": compression,
        },
        indent=2,
    ).encode("utf-8")
    info = tarfile.TarInfo("manifest.json")
    info.size = len(payload)
    info.mtime = int(datetime.now(UTC).timestamp())
    archive.addfile(info, io.BytesIO(payload))
