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
from safevault.ui.services import list_recent_modified_for_ui

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
    assert "SafeVault 后台保护未运行" in response.text
    assert "recover-home.txt" in response.text
    assert "CONFIRM" in response.text


def test_recovery_home_live_feed_shows_file_deleted_after_page_load(
    sv_home: Path, project: Path
) -> None:
    _complete_onboarding_config()
    target = project / "deleted-after-open.txt"
    target.write_text("recoverable", encoding="utf-8")
    create_snapshot(project)

    with TestClient(create_app(token=TOKEN)) as client:
        initial = client.get("/", params={"token": TOKEN})
        assert initial.status_code == 200
        before = client.get("/api/dashboard/recent")
        assert all(
            item["rel_path"] != "deleted-after-open.txt"
            for item in before.json()["deleted"]
        )

        target.unlink()
        create_snapshot(project)
        response = client.get("/api/dashboard/recent")

    assert response.status_code == 200
    matches = [
        item
        for item in response.json()["deleted"]
        if item["rel_path"] == "deleted-after-open.txt"
    ]
    assert len(matches) == 1
    assert matches[0]["absolute_path"] == str(target)


def test_recent_deleted_page_uses_local_time_and_live_feed(
    sv_home: Path, project: Path
) -> None:
    _complete_onboarding_config()
    target = project / "deleted-page-live.txt"
    target.write_text("recoverable", encoding="utf-8")
    create_snapshot(project)

    with TestClient(create_app(token=TOKEN)) as client:
        page = client.get("/deleted", params={"token": TOKEN})
        target.unlink()
        create_snapshot(project)
        feed = client.get("/api/deleted", params={"since": "24h"})

    assert page.status_code == 200
    assert 'data-deleted-live data-since="24h"' in page.text
    assert "data-local-zone" in page.text
    assert feed.status_code == 200
    matches = [
        item
        for item in feed.json()["deleted"]
        if item["rel_path"] == "deleted-page-live.txt"
    ]
    assert len(matches) == 1
    assert matches[0]["absolute_path"] == str(target)


def test_recovery_home_live_feed_keeps_recent_modified_unique(
    sv_home: Path, project: Path
) -> None:
    _complete_onboarding_config()
    target = project / "live-frequent.txt"
    target.write_text("one", encoding="utf-8")
    create_snapshot(project)
    target.write_text("two", encoding="utf-8")
    create_snapshot(project)
    target.write_text("three", encoding="utf-8")
    create_snapshot(project)

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.get("/api/dashboard/recent")

    assert response.status_code == 200
    matches = [
        item
        for item in response.json()["modified"]
        if item["rel_path"] == "live-frequent.txt"
    ]
    assert len(matches) == 1


def test_recovery_home_uses_plain_language_for_advanced_navigation(
    sv_home: Path,
) -> None:
    _complete_onboarding_config()

    with TestClient(create_app(token=TOKEN)) as client:
        response = client.get("/", params={"token": TOKEN})

    assert response.status_code == 200
    assert "AI 修改保护" in response.text
    assert "健康与清理" in response.text
    assert "外部备份" in response.text
    assert "data-dashboard-live" in response.text


def test_recovery_home_shows_version_timeline(sv_home: Path, project: Path) -> None:
    _complete_onboarding_config()
    target = project / "timeline-home.txt"
    target.write_text("first", encoding="utf-8")
    create_snapshot(project)
    target.write_text("second", encoding="utf-8")
    create_snapshot(project)

    with TestClient(create_app(token=TOKEN)) as client:
        response = client.get("/", params={"token": TOKEN})

    assert response.status_code == 200
    assert "恢复时间线" in response.text
    assert "timeline-home.txt" in response.text
    assert "Modified timeline-home.txt" in response.text


def test_recovery_home_searches_files(sv_home: Path, project: Path) -> None:
    _complete_onboarding_config()
    (project / "search-home.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)

    with TestClient(create_app(token=TOKEN)) as client:
        response = client.get("/", params={"token": TOKEN, "q": "search-home"})

    assert response.status_code == 200
    assert "search-home.txt" in response.text
    assert "查看历史" in response.text


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
    assert "正在监听" in response.text
    assert "已暂停" in response.text
    assert "目录不可用" in response.text
    assert "下次备份" in response.text
    assert "后台消息" in response.text
    assert "本地存储" in response.text
    assert "10 GB" in response.text


def test_recovery_home_recent_modified_lists_each_file_once(sv_home, project) -> None:
    target = project / "frequent.txt"
    target.write_text("one", encoding="utf-8")
    create_snapshot(project)
    target.write_text("two", encoding="utf-8")
    create_snapshot(project)
    target.write_text("three", encoding="utf-8")
    create_snapshot(project)

    rows = list_recent_modified_for_ui("24h")

    matches = [row for row in rows if row["rel_path"] == "frequent.txt"]
    assert len(matches) == 1


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
