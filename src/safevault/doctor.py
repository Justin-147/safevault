from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from safevault.db import connect
from safevault.object_store import iter_object_hashes, object_path
from safevault.paths import (
    ensure_home_layout,
    get_logs_dir,
    get_objects_dir,
    get_safevault_home,
    get_sandboxes_dir,
    get_tmp_dir,
)


@dataclass(frozen=True)
class DoctorResult:
    healthy: bool
    missing_objects: list[str]
    orphan_objects: list[str]
    temp_files: list[str]
    missing_roots: list[str]
    missing_tables: list[str]
    sandbox_warnings: list[str]

    @property
    def error_items(self) -> list[str]:
        return [
            *(f"missing referenced object: {item}" for item in self.missing_objects),
            *(f"missing table/directory: {item}" for item in self.missing_tables),
            *(f"missing root: {item}" for item in self.missing_roots),
        ]

    @property
    def warning_items(self) -> list[str]:
        return [
            *(f"orphan object: {item}" for item in self.orphan_objects),
            *(f"temp or partial file: {item}" for item in self.temp_files),
            *self.sandbox_warnings,
        ]

    def to_dict(self) -> dict[str, object]:
        return {
            "healthy": self.healthy,
            "errors": self.error_items,
            "warnings": self.warning_items,
            "missing_objects": self.missing_objects,
            "orphan_objects": self.orphan_objects,
            "temp_files": self.temp_files,
            "missing_roots": self.missing_roots,
            "missing_tables": self.missing_tables,
            "sandbox_warnings": self.sandbox_warnings,
        }


REQUIRED_TABLES = {"roots", "files", "snapshots", "versions", "events", "sandboxes"}


def run_doctor() -> DoctorResult:
    ensure_home_layout()
    conn = connect()
    try:
        table_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        tables = {str(row["name"]) for row in table_rows}
        missing_tables = sorted(REQUIRED_TABLES - tables)
        referenced = {
            str(row["content_hash"])
            for row in conn.execute(
                "SELECT DISTINCT content_hash FROM versions WHERE content_hash IS NOT NULL"
            ).fetchall()
        }
        missing_objects = sorted(
            content_hash for content_hash in referenced if not object_path(content_hash).is_file()
        )
        disk_objects = set(iter_object_hashes())
        orphan_objects = sorted(disk_objects - referenced)
        missing_roots = [
            str(row["path"])
            for row in conn.execute("SELECT path FROM roots ORDER BY path").fetchall()
            if not Path(row["path"]).exists()
        ]
    finally:
        conn.close()

    for required in (
        get_safevault_home(),
        get_objects_dir(),
        get_tmp_dir(),
        get_sandboxes_dir(),
        get_logs_dir(),
    ):
        if not required.exists():
            missing_tables.append(f"missing directory: {required}")

    temp_files = [
        str(path)
        for root in (get_objects_dir(), get_tmp_dir())
        if root.exists()
        for path in root.rglob("*")
        if path.is_file() and path.name.endswith((".tmp", ".partial"))
    ]
    sandbox_warnings = [
        f"sandbox without diff.json: {path}"
        for path in get_sandboxes_dir().iterdir()
        if path.is_dir() and not (path / "diff.json").is_file()
    ] if get_sandboxes_dir().exists() else []
    healthy = not missing_objects and not missing_tables and not missing_roots
    return DoctorResult(
        healthy=healthy,
        missing_objects=missing_objects,
        orphan_objects=orphan_objects,
        temp_files=temp_files,
        missing_roots=missing_roots,
        missing_tables=missing_tables,
        sandbox_warnings=sandbox_warnings,
    )
