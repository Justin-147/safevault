from __future__ import annotations

from conftest import make_symlink_or_skip
from safevault.db import connect
from safevault.snapshot import CaptureFailure, capture_entry_stable, create_snapshot


def test_normal_file_capture_succeeds(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("stable", encoding="utf-8")
    captured = capture_entry_stable(path, "file")
    assert captured is not None
    assert captured.size == len("stable")


def test_symlink_capture_does_not_follow_outside_root(sv_home, project, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("outside secret", encoding="utf-8")
    link = project / "link"
    make_symlink_or_skip(outside, link)
    captured = capture_entry_stable(link, "symlink")
    assert captured is not None
    assert captured.size != outside.stat().st_size


def test_unstable_file_is_skipped_and_snapshot_completes(
    sv_home, project, monkeypatch
) -> None:
    unstable = project / "unstable.txt"
    stable = project / "stable.txt"
    unstable.write_text("unstable", encoding="utf-8")
    stable.write_text("stable", encoding="utf-8")
    real_capture = capture_entry_stable

    def fake_capture(path, file_kind, max_retries=2):
        if path.name == "unstable.txt":
            return CaptureFailure("unstable")
        return real_capture(path, file_kind, max_retries)

    monkeypatch.setattr("safevault.snapshot.capture_entry_stable", fake_capture)
    create_snapshot(project)
    conn = connect()
    try:
        snapshot_status = conn.execute("SELECT status FROM snapshots").fetchone()["status"]
        events = {
            row["rel_path"]: row["event_type"]
            for row in conn.execute("SELECT rel_path, event_type FROM events")
        }
        files = {row["rel_path"] for row in conn.execute("SELECT rel_path FROM files")}
    finally:
        conn.close()
    assert snapshot_status == "complete"
    assert events["unstable.txt"] == "unstable"
    assert "stable.txt" in files
    assert "unstable.txt" not in files


def test_unchanged_stable_file_does_not_create_duplicate_versions(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("stable", encoding="utf-8")
    create_snapshot(project)
    create_snapshot(project)
    conn = connect()
    try:
        count = int(conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0])
    finally:
        conn.close()
    assert count == 1


def test_snapshot_continues_when_file_disappears_during_scan(
    sv_home, project, monkeypatch
) -> None:
    disappearing = project / "gone.txt"
    stable = project / "stable.txt"
    disappearing.write_text("gone", encoding="utf-8")
    stable.write_text("stable", encoding="utf-8")
    real_capture = capture_entry_stable

    def fake_capture(path, file_kind, max_retries=2):
        if path.name == "gone.txt":
            path.unlink(missing_ok=True)
            return CaptureFailure("missing")
        return real_capture(path, file_kind, max_retries)

    monkeypatch.setattr("safevault.snapshot.capture_entry_stable", fake_capture)
    create_snapshot(project)
    conn = connect()
    try:
        files = {row["rel_path"] for row in conn.execute("SELECT rel_path FROM files")}
    finally:
        conn.close()
    assert "stable.txt" in files
    assert "gone.txt" not in files


def test_snapshot_records_unreadable_event(sv_home, project, monkeypatch) -> None:
    path = project / "locked.txt"
    path.write_text("locked", encoding="utf-8")

    def fake_capture(_path, _file_kind, max_retries=2):
        return CaptureFailure("unreadable")

    monkeypatch.setattr("safevault.snapshot.capture_entry_stable", fake_capture)
    create_snapshot(project)
    conn = connect()
    try:
        row = conn.execute("SELECT event_type FROM events WHERE rel_path = 'locked.txt'").fetchone()
    finally:
        conn.close()
    assert row["event_type"] == "unreadable"


def test_tracked_file_disappearing_during_capture_gets_deleted_marker(
    sv_home, project, monkeypatch
) -> None:
    path = project / "tracked.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)

    def fake_capture(capture_path, _file_kind, max_retries=2):
        if capture_path.name == "tracked.txt":
            capture_path.unlink(missing_ok=True)
            return CaptureFailure("missing")
        return capture_entry_stable(capture_path, _file_kind, max_retries)

    monkeypatch.setattr("safevault.snapshot.capture_entry_stable", fake_capture)
    path.write_text("changed so capture runs", encoding="utf-8")
    create_snapshot(project)
    conn = connect()
    try:
        file_row = conn.execute(
            "SELECT status FROM files WHERE rel_path = 'tracked.txt'"
        ).fetchone()
        deleted_versions = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM versions
                WHERE rel_path = 'tracked.txt' AND is_deleted_marker = 1
                """
            ).fetchone()[0]
        )
    finally:
        conn.close()
    assert file_row["status"] == "deleted"
    assert deleted_versions == 1


def test_unreadable_existing_file_is_not_marked_deleted(
    sv_home, project, monkeypatch
) -> None:
    path = project / "locked.txt"
    path.write_text("tracked", encoding="utf-8")
    create_snapshot(project)

    def fake_capture(capture_path, _file_kind, max_retries=2):
        if capture_path.name == "locked.txt":
            return CaptureFailure("unreadable")
        return capture_entry_stable(capture_path, _file_kind, max_retries)

    monkeypatch.setattr("safevault.snapshot.capture_entry_stable", fake_capture)
    path.write_text("changed so capture runs", encoding="utf-8")
    create_snapshot(project)
    conn = connect()
    try:
        file_row = conn.execute("SELECT status FROM files WHERE rel_path = 'locked.txt'").fetchone()
        deleted_versions = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM versions
                WHERE rel_path = 'locked.txt' AND is_deleted_marker = 1
                """
            ).fetchone()[0]
        )
    finally:
        conn.close()
    assert file_row["status"] == "active"
    assert deleted_versions == 0
