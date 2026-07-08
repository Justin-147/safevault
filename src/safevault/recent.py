from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from safevault.db import connect, normalize_path
from safevault.durations import parse_duration
from safevault.errors import SafeVaultError


@dataclass(frozen=True)
class RecentEntry:
    root_path: str
    rel_path: str
    detected_at: str
    event_type: str
    size: int | None = None
    file_kind: str | None = None


@dataclass(frozen=True)
class SearchEntry:
    root_path: str
    rel_path: str
    status: str
    file_kind: str
    size: int | None
    last_seen_at: str


def list_recent_deleted(since: str = "24h", limit: int = 100) -> list[RecentEntry]:
    cutoff = _cutoff(since)
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT
                r.path AS root_path,
                v.rel_path AS rel_path,
                v.captured_at AS detected_at,
                'deleted' AS event_type,
                v.size AS size,
                f.file_kind AS file_kind
            FROM versions v
            JOIN files f ON f.id = v.file_id
            JOIN roots r ON r.id = f.root_id
            WHERE v.is_deleted_marker = 1 AND v.captured_at >= ?
            UNION
            SELECT
                r.path AS root_path,
                e.rel_path AS rel_path,
                e.detected_at AS detected_at,
                e.event_type AS event_type,
                NULL AS size,
                NULL AS file_kind
            FROM events e
            JOIN roots r ON r.id = e.root_id
            WHERE e.event_type = 'deleted' AND e.detected_at >= ?
            ORDER BY detected_at DESC
            LIMIT ?
            """,
            (cutoff, cutoff, limit),
        ).fetchall()
    finally:
        conn.close()
    return [_recent_from_row(row) for row in rows]


def list_recent_modified(since: str = "24h", limit: int = 100) -> list[RecentEntry]:
    cutoff = _cutoff(since)
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT
                r.path AS root_path,
                e.rel_path AS rel_path,
                e.detected_at AS detected_at,
                e.event_type AS event_type,
                f.size AS size,
                f.file_kind AS file_kind
            FROM events e
            JOIN roots r ON r.id = e.root_id
            LEFT JOIN files f ON f.root_id = e.root_id AND f.rel_path = e.rel_path
            WHERE e.event_type IN ('created', 'modified', 'restored')
              AND e.detected_at >= ?
            ORDER BY e.detected_at DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
    finally:
        conn.close()
    return [_recent_from_row(row) for row in rows]


def list_recent_activity(since: str = "24h", limit: int = 200) -> list[RecentEntry]:
    cutoff = _cutoff(since)
    conn = connect()
    try:
        rows = conn.execute(
            """
            SELECT
                r.path AS root_path,
                e.rel_path AS rel_path,
                e.detected_at AS detected_at,
                e.event_type AS event_type,
                f.size AS size,
                f.file_kind AS file_kind
            FROM events e
            JOIN roots r ON r.id = e.root_id
            LEFT JOIN files f ON f.root_id = e.root_id AND f.rel_path = e.rel_path
            WHERE e.detected_at >= ?
            ORDER BY e.detected_at DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()
    finally:
        conn.close()
    return [_recent_from_row(row) for row in rows]


def search_files(
    query: str,
    *,
    deleted: bool = False,
    root: Path | None = None,
    limit: int = 100,
) -> list[SearchEntry]:
    cleaned = query.strip()
    if not cleaned:
        raise SafeVaultError("search query must not be empty")
    params: list[object] = [f"%{cleaned}%"]
    filters = ["f.rel_path LIKE ?"]
    filters.append("f.status = ?")
    params.append("deleted" if deleted else "active")
    if root is not None:
        filters.append("r.path = ?")
        params.append(normalize_path(root))
    params.append(limit)
    conn = connect()
    try:
        rows = conn.execute(
            f"""
            SELECT
                r.path AS root_path,
                f.rel_path AS rel_path,
                f.status AS status,
                f.file_kind AS file_kind,
                f.size AS size,
                f.last_seen_at AS last_seen_at
            FROM files f
            JOIN roots r ON r.id = f.root_id
            WHERE {" AND ".join(filters)}
            ORDER BY f.last_seen_at DESC, f.rel_path
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
    finally:
        conn.close()
    return [
        SearchEntry(
            root_path=str(row["root_path"]),
            rel_path=str(row["rel_path"]),
            status=str(row["status"]),
            file_kind=str(row["file_kind"]),
            size=None if row["size"] is None else int(row["size"]),
            last_seen_at=str(row["last_seen_at"]),
        )
        for row in rows
    ]


def _cutoff(since: str) -> str:
    return (datetime.now(UTC) - parse_duration(since)).isoformat(timespec="microseconds")


def _recent_from_row(row) -> RecentEntry:
    return RecentEntry(
        root_path=str(row["root_path"]),
        rel_path=str(row["rel_path"]),
        detected_at=str(row["detected_at"]),
        event_type=str(row["event_type"]),
        size=None if row["size"] is None else int(row["size"]),
        file_kind=None if row["file_kind"] is None else str(row["file_kind"]),
    )
