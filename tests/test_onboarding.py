from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from safevault.config import load_config
from safevault.db import connect
from safevault.protection import add_protected_root
from safevault.ui.app import create_app

TOKEN = "test-token"


@pytest.fixture(autouse=True)
def _do_not_start_real_daemon(monkeypatch) -> None:
    monkeypatch.setattr("safevault.ui.services.ensure_daemon_running", lambda: False)


def test_first_open_shows_onboarding(sv_home: Path) -> None:
    with TestClient(create_app(token=TOKEN)) as client:
        response = client.get("/", params={"token": TOKEN})

    assert response.status_code == 200
    assert "欢迎使用 SafeVault" in response.text
    if os.name == "nt":
        assert "随 Windows 自动启动 SafeVault" in response.text
    else:
        assert "随 Windows 自动启动 SafeVault" not in response.text


def test_onboarding_completion_returns_without_synchronous_snapshot(
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
    assert "设置完成" in response.text
    assert "初始扫描正在后台进行" in response.text
    assert load_config().app.onboarding_completed is True
    conn = connect()
    try:
        root = conn.execute(
            "SELECT * FROM roots WHERE path = ?",
            (str(desktop.resolve()),),
        ).fetchone()
        snapshot_count = int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
    finally:
        conn.close()
    assert root is not None
    assert snapshot_count == 0


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


def test_onboarding_startup_option_installs_daemon_startup(
    sv_home: Path, monkeypatch
) -> None:
    calls = []
    monkeypatch.setattr(
        "safevault.ui.services.install_user_startup",
        lambda *, daemon, tray: calls.append((daemon, tray)),
    )
    monkeypatch.setattr("safevault.ui.services.startup_supported", lambda: True)

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/onboarding",
            data={
                "backup_schedule": "manual",
                "skip_roots": "true",
                "startup_enabled": "true",
            },
        )

    assert response.status_code == 200
    assert load_config().app.onboarding_completed is True
    assert calls == [(True, False)]


def test_onboarding_unchecked_startup_removes_existing_entry(
    sv_home: Path, monkeypatch
) -> None:
    calls = []
    monkeypatch.setattr("safevault.ui.services.startup_supported", lambda: True)
    monkeypatch.setattr(
        "safevault.ui.services.uninstall_user_startup",
        lambda *, daemon, tray: calls.append((daemon, tray)),
    )

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/onboarding",
            data={
                "backup_schedule": "manual",
                "skip_roots": "true",
                "startup_configured": "true",
            },
        )

    assert response.status_code == 200
    assert calls == [(True, False)]


def test_onboarding_recommends_pictures_when_present(
    sv_home: Path, tmp_path: Path, monkeypatch
) -> None:
    user_home = tmp_path / "user"
    pictures = user_home / "Pictures"
    pictures.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(user_home))

    with TestClient(create_app(token=TOKEN)) as client:
        response = client.get("/", params={"token": TOKEN})

    assert response.status_code == 200
    assert str(pictures.resolve()) in response.text
    assert f'value="{pictures.resolve()}" checked' in response.text


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
    assert "设置完成" in response.text
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


def test_onboarding_accepts_custom_root_and_profile(
    sv_home: Path, tmp_path: Path
) -> None:
    custom = tmp_path / "research"
    custom.mkdir()

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/onboarding",
            data={
                "custom_root_path": str(custom),
                "custom_root_profile": "documents",
                "backup_schedule": "manual",
            },
        )

    assert response.status_code == 200
    conn = connect()
    try:
        root = conn.execute(
            "SELECT * FROM roots WHERE path = ?", (str(custom.resolve()),)
        ).fetchone()
    finally:
        conn.close()
    assert root is not None
    assert root["profile"] == "documents"


def test_onboarding_requests_background_daemon_after_registering_root(
    sv_home: Path, tmp_path: Path, monkeypatch
) -> None:
    custom = tmp_path / "protected"
    custom.mkdir()
    calls = []
    monkeypatch.setattr(
        "safevault.ui.services.ensure_daemon_running",
        lambda: calls.append("daemon") or True,
    )

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/onboarding",
            data={
                "custom_root_path": str(custom),
                "custom_root_profile": "documents",
                "backup_schedule": "manual",
            },
        )

    assert response.status_code == 200
    assert calls == ["daemon"]


def test_onboarding_project_directory_is_optional_by_default(
    sv_home: Path, tmp_path: Path, monkeypatch
) -> None:
    user_home = tmp_path / "user"
    projects = user_home / "Projects"
    projects.mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(user_home))

    with TestClient(create_app(token=TOKEN)) as client:
        response = client.get("/", params={"token": TOKEN})

    assert response.status_code == 200
    assert f'value="{projects.resolve()}"' in response.text
    assert f'value="{projects.resolve()}" checked' not in response.text
    assert "再添加一个文件夹" in response.text
