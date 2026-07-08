from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from safevault import __version__
from safevault.errors import SafeVaultError

DIFF_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Root:
    id: int
    path: str
    created_at: str
    profile: str


@dataclass(frozen=True)
class ProtectionPolicy:
    id: int
    root_id: int
    root_path: str
    enabled: bool
    profile: str
    auto_snapshot: bool
    watch_enabled: bool
    hourly_snapshot: bool
    daily_snapshot: bool
    created_at: str
    updated_at: str
    paused_until: str | None = None


@dataclass(frozen=True)
class FileRecord:
    id: int
    root_id: int
    rel_path: str
    file_kind: str
    current_hash: str | None
    size: int | None
    mtime_ns: int | None
    mode: int | None
    last_seen_at: str
    status: str


@dataclass(frozen=True)
class SnapshotRecord:
    id: int
    root_id: int
    reason: str
    label: str | None
    started_at: str
    finished_at: str | None
    status: str


@dataclass(frozen=True)
class VersionRecord:
    id: int
    file_id: int
    snapshot_id: int
    rel_path: str
    content_hash: str | None
    size: int | None
    mtime_ns: int | None
    mode: int | None
    captured_at: str
    is_deleted_marker: int


@dataclass(frozen=True)
class EventRecord:
    id: int
    root_id: int
    event_type: str
    rel_path: str
    old_rel_path: str | None
    detected_at: str
    source: str


@dataclass(frozen=True)
class SandboxRecord:
    id: str
    root_id: int
    original_path: str
    sandbox_path: str
    created_at: str
    status: str


@dataclass(frozen=True)
class ApplyResult:
    applied: int
    deleted: int
    skipped_deletions: list[str]
    conflicts: list[str]
    unsafe: list[str]
    missing_sources: list[str]

    def __iter__(self):
        yield self.applied
        yield self.deleted
        yield self.skipped_deletions

    @property
    def has_skips(self) -> bool:
        return bool(
            self.skipped_deletions or self.conflicts or self.unsafe or self.missing_sources
        )


@dataclass(frozen=True)
class DiffEntry:
    rel_path: str
    change_type: str
    file_kind: str
    old_file_kind: str | None = None
    old_hash: str | None = None
    new_hash: str | None = None
    old_size: int | None = None
    new_size: int | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "rel_path": self.rel_path,
            "change_type": self.change_type,
            "file_kind": self.file_kind,
        }
        for key in ("old_file_kind", "old_hash", "new_hash", "old_size", "new_size"):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiffEntry:
        return cls(
            rel_path=str(data["rel_path"]),
            change_type=str(data["change_type"]),
            file_kind=str(data["file_kind"]),
            old_file_kind=(
                str(data["old_file_kind"]) if data.get("old_file_kind") is not None else None
            ),
            old_hash=data.get("old_hash") if data.get("old_hash") is not None else None,
            new_hash=data.get("new_hash") if data.get("new_hash") is not None else None,
            old_size=int(data["old_size"]) if data.get("old_size") is not None else None,
            new_size=int(data["new_size"]) if data.get("new_size") is not None else None,
        )


@dataclass(frozen=True)
class DiffResult:
    entries: list[DiffEntry]
    schema_version: int = DIFF_SCHEMA_VERSION
    created_at: str | None = None
    original_root: str | None = None
    sandbox_root: str | None = None
    safevault_version: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at
            or datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "original_root": self.original_root,
            "sandbox_root": self.sandbox_root,
            "safevault_version": self.safevault_version or __version__,
            "entries": [entry.to_dict() for entry in self.entries],
            "counts": self.counts(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiffResult:
        schema_version = data.get("schema_version")
        if schema_version is None:
            raise SafeVaultError(
                "diff.json missing schema_version; old diff.json files are unsupported"
            )
        if schema_version != DIFF_SCHEMA_VERSION:
            raise SafeVaultError(f"unsupported diff schema version: {schema_version!r}")
        for key in ("created_at", "original_root", "sandbox_root"):
            if not data.get(key):
                raise SafeVaultError(
                    f"diff.json missing {key}; old diff.json files are unsupported"
                )
        return cls(
            [DiffEntry.from_dict(item) for item in data.get("entries", [])],
            schema_version=int(schema_version),
            created_at=str(data["created_at"]) if data.get("created_at") is not None else None,
            original_root=(
                str(data["original_root"]) if data.get("original_root") is not None else None
            ),
            sandbox_root=(
                str(data["sandbox_root"]) if data.get("sandbox_root") is not None else None
            ),
            safevault_version=(
                str(data["safevault_version"])
                if data.get("safevault_version") is not None
                else None
            ),
        )

    def counts(self) -> dict[str, int]:
        counts = {"created": 0, "modified": 0, "deleted": 0}
        for entry in self.entries:
            counts[entry.change_type] = counts.get(entry.change_type, 0) + 1
        return counts

    def by_type(self, change_type: str) -> list[DiffEntry]:
        return [entry for entry in self.entries if entry.change_type == change_type]
