from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from safevault.config import load_config
from safevault.db import connect
from safevault.errors import SafeVaultError
from safevault.object_store import object_path
from safevault.retention import build_retention_plan
from safevault.retention_cleanup import (
    AUTO_CLEANUP_CONFIRMATION,
    apply_retention_cleanup,
    configure_retention,
    run_due_retention_cleanup,
)
from safevault.snapshot import create_snapshot


def test_legacy_default_migrates_to_seven_days_without_enabling_cleanup(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        "[retention]\nkeep_days = 90\nmax_vault_size_gb = 10\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.retention.keep_days == 7
    assert config.retention.auto_cleanup_enabled is False


def test_enabling_cleanup_requires_explicit_confirmation(sv_home) -> None:
    with pytest.raises(SafeVaultError, match=AUTO_CLEANUP_CONFIRMATION):
        configure_retention(keep_days=7, auto_cleanup_enabled=True)

    config = configure_retention(
        keep_days=7,
        auto_cleanup_enabled=True,
        confirmation=AUTO_CLEANUP_CONFIRMATION,
    )

    assert config.retention.auto_cleanup_enabled is True
    assert config.retention.keep_days == 7
    assert config.retention.last_cleanup_status == "pending"


def test_cleanup_requires_allow_delete_authorization(sv_home) -> None:
    with pytest.raises(SafeVaultError, match="--allow-delete"):
        apply_retention_cleanup(keep_days=7)


def test_cleanup_deletes_only_old_superseded_version_and_object(
    sv_home, project: Path
) -> None:
    path = project / "tracked.txt"
    path.write_text("old", encoding="utf-8")
    first = create_snapshot(project)
    old_version_id, old_hash = _version_for_snapshot(first)
    _age_snapshot(first, days=8)

    path.write_text("new", encoding="utf-8")
    second = create_snapshot(project)
    latest_version_id, latest_hash = _version_for_snapshot(second)

    result = apply_retention_cleanup(keep_days=7, allow_delete=True)

    assert result.deleted_versions == 1
    assert result.deleted_snapshots == 1
    assert result.deleted_objects == 1
    assert not object_path(old_hash).exists()
    assert object_path(latest_hash).is_file()
    conn = connect()
    try:
        assert conn.execute(
            "SELECT 1 FROM versions WHERE id = ?", (old_version_id,)
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM versions WHERE id = ?", (latest_version_id,)
        ).fetchone() is not None
    finally:
        conn.close()


def test_cleanup_preserves_latest_deleted_file_version(sv_home, project: Path) -> None:
    path = project / "deleted.txt"
    path.write_text("recoverable", encoding="utf-8")
    first = create_snapshot(project)
    version_id, content_hash = _version_for_snapshot(first)
    path.unlink()
    create_snapshot(project)
    _age_snapshot(first, days=30)
    _age_all_versions(days=30)

    result = apply_retention_cleanup(keep_days=7, allow_delete=True)

    assert result.deleted_versions == 0
    assert object_path(content_hash).is_file()
    conn = connect()
    try:
        assert conn.execute(
            "SELECT 1 FROM versions WHERE id = ?", (version_id,)
        ).fetchone() is not None
    finally:
        conn.close()


def test_cleanup_preserves_important_restore_point(sv_home, project: Path) -> None:
    path = project / "important.txt"
    path.write_text("important", encoding="utf-8")
    first = create_snapshot(project)
    _age_snapshot(first, days=30)
    conn = connect()
    try:
        conn.execute(
            "UPDATE restore_points SET important = 1 WHERE snapshot_id = ?",
            (first,),
        )
        conn.commit()
    finally:
        conn.close()
    path.write_text("new", encoding="utf-8")
    create_snapshot(project)

    plan = build_retention_plan(keep_days=7)
    result = apply_retention_cleanup(keep_days=7, allow_delete=True)

    assert plan.candidate_versions == []
    assert result.deleted_versions == 0


def test_cleanup_keeps_shared_object_still_referenced_by_latest_version(
    sv_home, project: Path
) -> None:
    first_path = project / "first.txt"
    second_path = project / "second.txt"
    first_path.write_text("shared", encoding="utf-8")
    second_path.write_text("shared", encoding="utf-8")
    first = create_snapshot(project)
    _age_snapshot(first, days=8)
    first_path.write_text("replacement", encoding="utf-8")
    create_snapshot(project)
    conn = connect()
    try:
        shared_hash = str(
            conn.execute(
                "SELECT current_hash FROM files WHERE rel_path = 'second.txt'"
            ).fetchone()[0]
        )
    finally:
        conn.close()

    result = apply_retention_cleanup(keep_days=7, allow_delete=True)

    assert result.deleted_versions == 1
    assert result.deleted_objects == 0
    assert object_path(shared_hash).is_file()


def test_due_cleanup_runs_at_most_once_per_day_and_records_result(
    sv_home, project: Path
) -> None:
    path = project / "scheduled.txt"
    path.write_text("old", encoding="utf-8")
    first = create_snapshot(project)
    _age_snapshot(first, days=8)
    path.write_text("new", encoding="utf-8")
    create_snapshot(project)
    configure_retention(
        keep_days=7,
        auto_cleanup_enabled=True,
        confirmation=AUTO_CLEANUP_CONFIRMATION,
    )
    now = datetime.now(UTC)

    first_run = run_due_retention_cleanup(now=now)
    second_run = run_due_retention_cleanup(now=now + timedelta(hours=23))

    assert first_run is not None
    assert first_run.deleted_versions == 1
    assert second_run is None
    config = load_config()
    assert config.retention.last_cleanup_status == "success"
    assert config.retention.last_cleanup_deleted_versions == 1


def _version_for_snapshot(snapshot_id: int) -> tuple[int, str]:
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT id, content_hash FROM versions
            WHERE snapshot_id = ? AND content_hash IS NOT NULL
            ORDER BY id LIMIT 1
            """,
            (snapshot_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return int(row["id"]), str(row["content_hash"])


def _age_snapshot(snapshot_id: int, *, days: int) -> None:
    old = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="microseconds")
    conn = connect()
    try:
        conn.execute(
            "UPDATE snapshots SET started_at = ?, finished_at = ? WHERE id = ?",
            (old, old, snapshot_id),
        )
        conn.execute(
            "UPDATE versions SET captured_at = ? WHERE snapshot_id = ?",
            (old, snapshot_id),
        )
        conn.execute(
            "UPDATE restore_points SET created_at = ? WHERE snapshot_id = ?",
            (old, snapshot_id),
        )
        conn.commit()
    finally:
        conn.close()


def _age_all_versions(*, days: int) -> None:
    old = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="microseconds")
    conn = connect()
    try:
        conn.execute("UPDATE versions SET captured_at = ?", (old,))
        conn.commit()
    finally:
        conn.close()
