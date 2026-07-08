from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from safevault.backup import configure_backup
from safevault.config import load_config, save_config
from safevault.daemon import run_daemon
from safevault.protection import add_protected_root
from safevault.snapshot import create_snapshot
from safevault.ui.app import create_app

TOKEN = "test-token"


def _complete_onboarding_config() -> None:
    config = load_config()
    save_config(replace(config, app=replace(config.app, onboarding_completed=True)))


def test_recovery_home_shows_recent_deleted_and_modified(
    sv_home: Path, project: Path
) -> None:
    _complete_onboarding_config()
    target = project / "recover-home.txt"
    target.write_text("one", encoding="utf-8")
    create_snapshot(project)
    target.write_text("two", encoding="utf-8")
    create_snapshot(project)
    target.unlink()
    create_snapshot(project)

    with TestClient(create_app(token=TOKEN)) as client:
        response = client.get("/", params={"token": TOKEN})

    assert response.status_code == 200
    assert "SafeVault 正在保护你的文件" in response.text
    assert "recover-home.txt" in response.text
    assert "CONFIRM" in response.text


def test_recovery_home_searches_files(sv_home: Path, project: Path) -> None:
    _complete_onboarding_config()
    (project / "search-home.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)

    with TestClient(create_app(token=TOKEN)) as client:
        response = client.get("/", params={"token": TOKEN, "q": "search-home"})

    assert response.status_code == 200
    assert "search-home.txt" in response.text
    assert "Versions" in response.text


def test_dashboard_displays_daemon_and_backup_details(
    sv_home: Path, project: Path, tmp_path: Path
) -> None:
    _complete_onboarding_config()
    add_protected_root(project, "coding")
    configure_backup(tmp_path / "dashboard-backups", "daily", time="00:00")
    run_daemon(test_once=True)

    with TestClient(create_app(token=TOKEN)) as client:
        response = client.get("/", params={"token": TOKEN})

    assert response.status_code == 200
    assert "Watched roots" in response.text
    assert "Paused roots" in response.text
    assert "Missing roots" in response.text
    assert "Next backup due" in response.text
    assert "Daemon message" in response.text


def test_one_click_restore_uses_normal_confirmation(sv_home: Path, project: Path) -> None:
    _complete_onboarding_config()
    target = project / "one-click.txt"
    target.write_text("first", encoding="utf-8")
    create_snapshot(project)
    target.write_text("second", encoding="utf-8")
    create_snapshot(project)
    target.unlink()
    create_snapshot(project)

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/restore",
            data={"file": str(target), "mode": "latest", "confirmation": "CONFIRM"},
        )

    assert response.status_code == 200
    assert "Restored to" in response.text
    assert target.read_text(encoding="utf-8") == "second"


def test_recovery_home_restore_button_has_confirm_dialog(
    sv_home: Path, project: Path
) -> None:
    _complete_onboarding_config()
    target = project / "confirm-restore.txt"
    target.write_text("first", encoding="utf-8")
    create_snapshot(project)
    target.unlink()
    create_snapshot(project)

    with TestClient(create_app(token=TOKEN)) as client:
        response = client.get("/", params={"token": TOKEN})

    assert response.status_code == 200
    assert "onclick=\"return confirm(" in response.text
