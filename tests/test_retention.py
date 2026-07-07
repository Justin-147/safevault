from __future__ import annotations

from datetime import UTC, datetime, timedelta

from safevault.cli import app
from safevault.db import connect
from safevault.retention import build_retention_plan
from safevault.snapshot import create_snapshot


def test_retention_never_proposes_latest_active_version(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    _age_all_versions(days=120)
    plan = build_retention_plan(keep_days=90)
    assert plan.candidate_versions == []


def test_retention_never_proposes_latest_restorable_deleted_version(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    path.unlink()
    create_snapshot(project)
    _age_all_versions(days=120)
    plan = build_retention_plan(keep_days=90)
    assert plan.candidate_versions == []


def test_retention_proposes_old_superseded_versions(sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    _age_versions([1], days=120)
    path.write_text("v2", encoding="utf-8")
    create_snapshot(project)
    plan = build_retention_plan(keep_days=90)
    assert [item.version_id for item in plan.candidate_versions] == [1]


def test_retention_plan_cli_is_non_destructive(runner, sv_home, project) -> None:
    path = project / "a.txt"
    path.write_text("v1", encoding="utf-8")
    create_snapshot(project)
    _age_versions([1], days=120)
    path.write_text("v2", encoding="utf-8")
    create_snapshot(project)
    before = _counts()
    result = runner.invoke(app, ["retention-plan", "--keep-days", "90", "--verbose"])
    after = _counts()
    assert result.exit_code == 0
    assert "Candidate versions: 1" in result.output
    assert before == after


def _age_all_versions(*, days: int) -> None:
    conn = connect()
    try:
        ids = [int(row["id"]) for row in conn.execute("SELECT id FROM versions")]
    finally:
        conn.close()
    _age_versions(ids, days=days)


def _age_versions(ids: list[int], *, days: int) -> None:
    old = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="microseconds")
    conn = connect()
    try:
        for version_id in ids:
            conn.execute(
                "UPDATE versions SET captured_at = ? WHERE id = ?", (old, version_id)
            )
            conn.execute(
                """
                UPDATE snapshots
                SET started_at = ?, finished_at = ?
                WHERE id = (SELECT snapshot_id FROM versions WHERE id = ?)
                """,
                (old, old, version_id),
            )
        conn.commit()
    finally:
        conn.close()


def _counts() -> tuple[int, int]:
    conn = connect()
    try:
        versions = int(conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0])
        snapshots = int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
        return versions, snapshots
    finally:
        conn.close()
