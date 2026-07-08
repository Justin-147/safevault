from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from safevault.config import load_config
from safevault.db import connect
from safevault.protection import add_protected_root
from safevault.ui.app import create_app

TOKEN = "test-token"


def test_first_open_shows_onboarding(sv_home: Path) -> None:
    with TestClient(create_app(token=TOKEN)) as client:
        response = client.get("/", params={"token": TOKEN})

    assert response.status_code == 200
    assert "首次启动向导" in response.text


def test_onboarding_completion_writes_config_and_initial_snapshot(
    sv_home: Path, tmp_path: Path, monkeypatch
) -> None:
    user_home = tmp_path / "user"
    desktop = user_home / "Desktop"
    desktop.mkdir(parents=True)
    (desktop / "hello.txt").write_text("tracked", encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(user_home))

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/onboarding",
            data={"roots": str(desktop), "backup_schedule": "manual"},
        )

    assert response.status_code == 200
    assert "Onboarding complete" in response.text
    assert load_config().app.onboarding_completed is True
    conn = connect()
    try:
        root = conn.execute(
            "SELECT * FROM roots WHERE path = ?",
            (str(desktop.resolve()),),
        ).fetchone()
        snapshot = conn.execute(
            "SELECT * FROM snapshots WHERE reason = 'onboarding-initial'"
        ).fetchone()
    finally:
        conn.close()
    assert root is not None
    assert snapshot is not None


def test_onboarding_can_configure_backup(sv_home: Path, tmp_path: Path) -> None:
    backup_target = tmp_path / "backups"

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/onboarding",
            data={
                "backup_target": str(backup_target),
                "backup_schedule": "weekly",
                "skip_roots": "true",
            },
        )

    assert response.status_code == 200
    config = load_config()
    assert config.app.onboarding_completed is True
    assert config.backup.enabled is True
    assert config.backup.schedule == "weekly"
    assert config.backup.target == str(backup_target.resolve(strict=False))


def test_onboarding_requires_root_or_explicit_skip(sv_home: Path) -> None:
    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/onboarding",
            data={"backup_schedule": "manual"},
        )

    assert response.status_code == 200
    assert "select at least one protected root" in response.text
    assert load_config().app.onboarding_completed is False


def test_onboarding_can_complete_with_existing_root(
    sv_home: Path, project: Path
) -> None:
    add_protected_root(project, "coding")

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/onboarding",
            data={"roots": str(project), "backup_schedule": "manual"},
        )

    assert response.status_code == 200
    assert "Onboarding complete" in response.text
    assert load_config().app.onboarding_completed is True


def test_onboarding_rejects_unsafe_root_without_side_effects(sv_home: Path) -> None:
    sv_home.mkdir(parents=True, exist_ok=True)

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/onboarding",
            data={"roots": str(sv_home), "backup_schedule": "manual"},
        )

    assert response.status_code == 200
    assert "SAFEVAULT_HOME" in response.text
    assert load_config().app.onboarding_completed is False
    conn = connect()
    try:
        assert int(conn.execute("SELECT COUNT(*) FROM roots").fetchone()[0]) == 0
        assert int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]) == 0
    finally:
        conn.close()
