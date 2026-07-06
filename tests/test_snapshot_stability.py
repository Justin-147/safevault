from __future__ import annotations

from conftest import make_symlink_or_skip
from safevault.db import connect
from safevault.snapshot import capture_entry_stable, create_snapshot


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
            return None
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
