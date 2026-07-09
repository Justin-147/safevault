from __future__ import annotations

from pathlib import Path

from safevault.daemon import record_moved_event
from safevault.db import connect
from safevault.snapshot import create_snapshot


def _rows(table: str):
    conn = connect()
    try:
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table}").fetchall()]
    finally:
        conn.close()


def test_continuous_timeline_records_created_modified_deleted(
    sv_home: Path, project: Path
) -> None:
    target = project / "timeline.txt"
    target.write_text("one", encoding="utf-8")
    create_snapshot(project, reason="continuous-initial")
    target.write_text("two", encoding="utf-8")
    create_snapshot(project, reason="continuous-modified")
    target.unlink()
    create_snapshot(project, reason="continuous-deleted")

    events = _rows("file_events")
    timeline = _rows("version_timeline")
    restore_points = _rows("restore_points")

    assert [event["event_type"] for event in events] == [
        "created",
        "modified",
        "deleted",
    ]
    assert [item["event_type"] for item in timeline] == [
        "created",
        "modified",
        "deleted",
    ]
    assert len(restore_points) == 3
    assert restore_points[-1]["reason"] == "continuous-deleted"


def test_moved_event_records_old_and_new_path(sv_home: Path, project: Path) -> None:
    source = project / "old.txt"
    dest = project / "new.txt"
    source.write_text("tracked", encoding="utf-8")
    create_snapshot(project)

    assert record_moved_event(project, source, dest) is True

    events = _rows("file_events")
    moved = [event for event in events if event["event_type"] == "moved"]
    assert moved
    assert moved[-1]["old_rel_path"] == "old.txt"
    assert moved[-1]["rel_path"] == "new.txt"
