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
from safevault.errors import SafeVaultError
from safevault.object_store import iter_object_hashes, object_path
from safevault.paths import ensure_home_layout, get_db_path, get_safevault_home


@dataclass(frozen=True)
class ExportResult:
    output: Path
    object_count: int


def export_vault(
    *, output: Path, gzip: bool = False, allow_inside_vault: bool = False
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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f".{output_path.name}.tmp")
    object_hashes = sorted(iter_object_hashes())
    try:
        with tarfile.open(tmp_path, "w:gz" if gzip else "w") as archive:
            db_path = get_db_path()
            if db_path.is_file():
                archive.add(db_path, arcname="vault.db")
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
            _add_manifest(archive, len(object_hashes))
        os.replace(tmp_path, output_path)
        fsync_dir(output_path.parent)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
    return ExportResult(output=output_path, object_count=len(object_hashes))


def _add_manifest(archive: tarfile.TarFile, object_count: int) -> None:
    payload = json.dumps(
        {
            "created_at": datetime.now(UTC).isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
            "safevault_version": __version__,
            "object_count": object_count,
            "database": "vault.db",
        },
        indent=2,
    ).encode("utf-8")
    info = tarfile.TarInfo("manifest.json")
    info.size = len(payload)
    info.mtime = int(datetime.now(UTC).timestamp())
    archive.addfile(info, io.BytesIO(payload))
