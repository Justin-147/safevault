from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DashboardStatus:
    version: str
    safevault_home: str
    doctor_healthy: bool
    verify_healthy: bool
    roots_count: int
    snapshots_count: int
    active_files_count: int
    deleted_files_count: int
    object_store_size: int
    latest_sandbox: dict[str, str] | None
    daemon_status: str
    watched_roots: int
    paused_roots: int
    missing_roots: int
    last_daemon_message: str | None
    last_snapshot: str | None
    last_backup: str | None
    next_backup_due: str | None
    health_summary: str


@dataclass(frozen=True)
class RootSummary:
    id: int
    path: str
    profile: str
    exists: bool
    active_count: int
    deleted_count: int
    last_snapshot: str | None


@dataclass(frozen=True)
class RootDetail:
    root: RootSummary
    snapshots: list[dict[str, object]]
    deleted_markers: list[dict[str, object]]


@dataclass(frozen=True)
class VersionEntry:
    version_id: int
    captured_at: str
    size: int | None
    content_hash: str | None
    deleted: bool
    file_kind: str


@dataclass(frozen=True)
class DeletedEntry:
    root_path: str
    rel_path: str
    absolute_path: str
    detected_at: str


@dataclass(frozen=True)
class TimelineEntry:
    root_path: str
    rel_path: str
    event_type: str
    title: str
    occurred_at: str


@dataclass(frozen=True)
class SandboxSummary:
    id: str
    original_path: str
    sandbox_path: str
    created_at: str
    status: str
    counts: dict[str, int]
