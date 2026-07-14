from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from safevault.config import load_config, save_config
from safevault.snapshot import create_snapshot
from safevault.ui.app import create_app

TOKEN = "test-token"


def _complete_onboarding() -> None:
    config = load_config()
    save_config(replace(config, app=replace(config.app, onboarding_completed=True)))


def test_storage_page_shows_location_budget_and_analysis(
    sv_home: Path, project: Path
) -> None:
    _complete_onboarding()
    (project / "tracked.bin").write_bytes(b"x" * 2048)
    create_snapshot(project)

    with TestClient(create_app(token=TOKEN)) as client:
        response = client.get("/storage", params={"token": TOKEN})

    assert response.status_code == 200
    assert "存储管理" in response.text
    assert str(sv_home) in response.text
    assert "最低可恢复体积" in response.text
    assert "tracked.bin" in response.text


def test_storage_budget_can_be_updated_from_ui(sv_home: Path) -> None:
    _complete_onboarding()

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/storage", params={"token": TOKEN})
        response = client.post("/storage/budget", data={"budget_gb": "12"})

    assert response.status_code == 200
    assert load_config().retention.max_vault_size_gb == 12


def test_storage_retention_ui_requires_confirmation_and_enables_cleanup(
    sv_home: Path,
) -> None:
    _complete_onboarding()

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/storage", params={"token": TOKEN})
        rejected = client.post(
            "/storage/retention",
            data={"keep_days": "7", "auto_cleanup_enabled": "true"},
        )
        accepted = client.post(
            "/storage/retention",
            data={
                "keep_days": "7",
                "auto_cleanup_enabled": "true",
                "confirmation": "ENABLE AUTO CLEANUP",
            },
        )

    assert rejected.status_code == 200
    assert "ENABLE AUTO CLEANUP" in rejected.text
    assert accepted.status_code == 200
    assert "自动清理已启用" in accepted.text
    config = load_config()
    assert config.retention.keep_days == 7
    assert config.retention.auto_cleanup_enabled is True


def test_storage_migration_ui_requires_confirmation_before_removing_source(
    sv_home: Path, tmp_path: Path
) -> None:
    _complete_onboarding()

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/storage", params={"token": TOKEN})
        response = client.post(
            "/storage/migrate",
            data={
                "destination": str(tmp_path / "new-storage"),
                "remove_source": "true",
                "confirmation": "wrong",
            },
        )

    assert response.status_code == 200
    assert "MOVE STORAGE" in response.text
