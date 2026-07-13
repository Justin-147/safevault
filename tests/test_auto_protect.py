from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from safevault.cli import app
from safevault.config import BackupConfig, SafeVaultConfig, load_config, save_config
from safevault.db import connect, get_or_create_root
from safevault.doctor import run_doctor
from safevault.snapshot import create_snapshot


def test_schema_migration_adds_auto_protection_tables(sv_home) -> None:
    conn = connect()
    try:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        migrations = {
            int(row["version"])
            for row in conn.execute("SELECT version FROM schema_migrations")
        }
    finally:
        conn.close()

    assert version == 6
    assert {
        "schema_migrations",
        "protection_policies",
        "daemon_state",
        "change_batches",
        "backup_jobs",
        "notifications",
        "file_events",
        "version_timeline",
        "restore_points",
        "ai_change_sessions",
    } <= tables
    assert {2, 3, 4, 5, 6} <= migrations


def test_config_round_trips_extended_settings(sv_home, tmp_path: Path) -> None:
    backup_target = tmp_path / "external-backup"
    config = SafeVaultConfig(
        backup=BackupConfig(enabled=True, target=str(backup_target), schedule="daily")
    )
    save_config(config)

    loaded = load_config()

    assert loaded.backup.enabled is True
    assert loaded.backup.schedule == "daily"
    assert loaded.backup.target == str(backup_target.resolve(strict=False))
    assert (sv_home / "config.toml").is_file()


def test_config_rejects_backup_target_inside_safevault_home(sv_home) -> None:
    config = SafeVaultConfig(
        backup=BackupConfig(enabled=True, target=str(sv_home / "backups"))
    )

    try:
        save_config(config)
    except Exception as exc:
        assert "SAFEVAULT_HOME" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected backup target under SAFEVAULT_HOME to fail")


def test_protect_add_list_and_remove_preserves_root(runner, sv_home, project) -> None:
    add_result = runner.invoke(app, ["protect", "add", str(project), "--profile", "coding"])
    assert add_result.exit_code == 0
    assert "Protected root" in add_result.output

    list_result = runner.invoke(app, ["protect", "list", "--json"])
    assert list_result.exit_code == 0
    policies = json.loads(list_result.output)
    assert policies[0]["path"] == str(project.resolve())
    assert policies[0]["enabled"] is True

    remove_result = runner.invoke(app, ["protect", "remove", str(project), "--confirm"])
    assert remove_result.exit_code == 0
    assert "Disabled automatic protection" in remove_result.output

    list_after_remove = runner.invoke(app, ["protect", "list", "--json"])
    assert list_after_remove.exit_code == 0
    policies = json.loads(list_after_remove.output)
    assert policies[0]["enabled"] is False

    roots_result = runner.invoke(app, ["roots", "--json"])
    assert roots_result.exit_code == 0
    assert json.loads(roots_result.output)[0]["path"] == str(project.resolve())


def test_protect_remove_requires_confirm(runner, sv_home, project) -> None:
    assert runner.invoke(app, ["protect", "add", str(project)]).exit_code == 0

    result = runner.invoke(app, ["protect", "remove", str(project)])

    assert result.exit_code != 0
    assert "pass --confirm" in result.output


def test_protect_add_rejects_duplicate_root(runner, sv_home, project) -> None:
    assert runner.invoke(app, ["protect", "add", str(project)]).exit_code == 0

    result = runner.invoke(app, ["protect", "add", str(project)])

    assert result.exit_code != 0
    assert "already protected" in result.output


def test_protect_add_reenables_disabled_root(runner, sv_home, project) -> None:
    added = runner.invoke(app, ["protect", "add", str(project), "--profile", "coding"])
    assert added.exit_code == 0
    assert runner.invoke(app, ["protect", "remove", str(project), "--confirm"]).exit_code == 0

    result = runner.invoke(
        app,
        ["protect", "add", str(project), "--profile", "documents", "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["reenabled"] is True
    policies = json.loads(runner.invoke(app, ["protect", "list", "--json"]).output)
    assert policies[0]["enabled"] is True
    assert policies[0]["watch_enabled"] is True
    assert policies[0]["paused_until"] is None
    assert policies[0]["profile"] == "documents"


def test_protect_add_rejects_safevault_home(runner, sv_home) -> None:
    sv_home.mkdir(parents=True)

    result = runner.invoke(app, ["protect", "add", str(sv_home)])

    assert result.exit_code != 0
    assert "SAFEVAULT_HOME" in result.output


def test_init_rejects_safevault_home(runner, sv_home) -> None:
    sv_home.mkdir(parents=True)

    result = runner.invoke(app, ["init", str(sv_home)])

    assert result.exit_code != 0
    assert "SAFEVAULT_HOME" in result.output


def test_snapshot_rejects_filesystem_root_when_auto_registering(
    runner, sv_home, tmp_path: Path
) -> None:
    result = runner.invoke(app, ["snapshot", tmp_path.anchor])

    assert result.exit_code != 0
    assert "filesystem root" in result.output


def test_protect_add_rejects_backup_target(runner, sv_home, project, tmp_path: Path) -> None:
    backup_target = tmp_path / "backup-target"
    backup_target.mkdir()
    save_config(
        replace(
            SafeVaultConfig(),
            backup=BackupConfig(enabled=True, target=str(backup_target)),
        )
    )

    result = runner.invoke(app, ["protect", "add", str(backup_target)])

    assert result.exit_code != 0
    assert "backup target" in result.output


def test_protect_list_marks_unsafe_legacy_root(runner, sv_home) -> None:
    sv_home.mkdir(parents=True)
    conn = connect()
    try:
        get_or_create_root(conn, sv_home, "coding")
    finally:
        conn.close()

    result = runner.invoke(app, ["protect", "list", "--json"])

    assert result.exit_code == 0
    rows = json.loads(result.output)
    assert rows[0]["unsafe"] is True
    assert "SAFEVAULT_HOME" in rows[0]["safety_issue"]


def test_doctor_reports_unsafe_root(sv_home) -> None:
    sv_home.mkdir(parents=True)
    conn = connect()
    try:
        get_or_create_root(conn, sv_home, "coding")
    finally:
        conn.close()

    result = run_doctor()

    assert any("SAFEVAULT_HOME" in item for item in result.warning_items)


def test_snapshot_rejects_safevault_home_when_auto_registering(sv_home) -> None:
    sv_home.mkdir(parents=True)

    try:
        create_snapshot(sv_home)
    except Exception as exc:
        assert "SAFEVAULT_HOME" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected snapshot of SAFEVAULT_HOME to fail")


def test_protect_add_rejects_filesystem_root(runner, sv_home, tmp_path: Path) -> None:
    result = runner.invoke(app, ["protect", "add", tmp_path.anchor])

    assert result.exit_code != 0
    assert "filesystem root" in result.output


def test_protect_add_rejects_generated_directory_name(runner, sv_home, tmp_path: Path) -> None:
    generated = tmp_path / "node_modules"
    generated.mkdir()

    result = runner.invoke(app, ["protect", "add", str(generated)])

    assert result.exit_code != 0
    assert "generated or internal directory" in result.output


def test_protect_auto_detect_lists_existing_safe_candidates(
    runner, sv_home, tmp_path: Path, monkeypatch
) -> None:
    user_home = tmp_path / "user"
    desktop = user_home / "Desktop"
    documents = user_home / "Documents"
    projects = user_home / "Projects"
    desktop.mkdir(parents=True)
    documents.mkdir()
    projects.mkdir()
    monkeypatch.setenv("USERPROFILE", str(user_home))

    result = runner.invoke(app, ["protect", "auto-detect", "--json"])

    assert result.exit_code == 0
    paths = {item["path"]: item for item in json.loads(result.output)}
    assert str(desktop.resolve()) in paths
    assert paths[str(desktop.resolve())]["profile"] == "desktop"
    assert str(documents.resolve()) in paths
    assert str(projects.resolve()) in paths
