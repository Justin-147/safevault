from __future__ import annotations

import json

from safevault.cli import app
from safevault.snapshot import create_snapshot


def test_recent_deleted_reports_deleted_marker(runner, sv_home, project) -> None:
    target = project / "lost.txt"
    target.write_text("hello", encoding="utf-8")
    create_snapshot(project)
    target.unlink()
    create_snapshot(project)

    result = runner.invoke(app, ["recent", "deleted", "--since", "24h", "--json"])

    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert any(row["rel_path"] == "lost.txt" for row in rows)


def test_recent_modified_reports_created_and_modified_events(runner, sv_home, project) -> None:
    target = project / "notes.txt"
    target.write_text("one", encoding="utf-8")
    create_snapshot(project)
    target.write_text("two", encoding="utf-8")
    create_snapshot(project)

    result = runner.invoke(app, ["recent", "modified", "--since", "24h", "--json"])

    assert result.exit_code == 0
    rows = json.loads(result.output)
    events = {row["event_type"] for row in rows if row["rel_path"] == "notes.txt"}
    assert "created" in events
    assert "modified" in events


def test_recent_activity_includes_deleted_events(runner, sv_home, project) -> None:
    target = project / "activity.txt"
    target.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    target.unlink()
    create_snapshot(project)

    result = runner.invoke(app, ["recent", "activity", "--since", "24h", "--json"])

    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert any(
        row["rel_path"] == "activity.txt" and row["event_type"] == "deleted"
        for row in rows
    )


def test_legacy_deleted_command_uses_recent_query(runner, sv_home, project) -> None:
    target = project / "legacy.txt"
    target.write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    target.unlink()
    create_snapshot(project)

    result = runner.invoke(app, ["deleted", "--since", "24h"])

    assert result.exit_code == 0
    assert "legacy.txt" in result.output
