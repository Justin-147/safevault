from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from safevault.config import BackupConfig, SafeVaultConfig, load_config, save_config
from safevault.db import connect
from safevault.errors import SafeVaultError
from safevault.protection import add_protected_root, remove_protected_root
from safevault.sandbox import create_sandbox
from safevault.snapshot import create_snapshot
from safevault.ui.app import create_app
from safevault.ui.auth import UI_COOKIE_NAME
from safevault.ui.services import unprotect_from_ui

TOKEN = "test-token"


@pytest.fixture(autouse=True)
def _do_not_start_real_daemon(monkeypatch) -> None:
    monkeypatch.setattr("safevault.ui.services.ensure_daemon_running", lambda: False)


def _root_id_for(path: Path) -> int:
    conn = connect()
    try:
        row = conn.execute("SELECT id FROM roots WHERE path = ?", (str(path.resolve()),)).fetchone()
        assert row is not None
        return int(row["id"])
    finally:
        conn.close()


def _sandbox_status(sandbox_id: str) -> str:
    conn = connect()
    try:
        row = conn.execute(
            "SELECT status FROM sandboxes WHERE id = ?", (sandbox_id,)
        ).fetchone()
        assert row is not None
        return str(row["status"])
    finally:
        conn.close()


def _version_count() -> int:
    conn = connect()
    try:
        return int(conn.execute("SELECT COUNT(*) FROM versions").fetchone()[0])
    finally:
        conn.close()


def _root_count() -> int:
    conn = connect()
    try:
        return int(conn.execute("SELECT COUNT(*) FROM roots").fetchone()[0])
    finally:
        conn.close()


def test_ui_requires_token_sets_cookie_and_serves_pages(sv_home: Path) -> None:
    with TestClient(create_app(token=TOKEN)) as client:
        assert client.get("/").status_code == 403

        response = client.get("/", params={"token": TOKEN})
        assert response.status_code == 200
        assert UI_COOKIE_NAME in client.cookies
        assert "Local UI only. Not a remote admin console." in response.text

        for path in (
            "/roots",
            "/versions",
            "/deleted",
            "/sandboxes",
            "/maintenance",
            "/export-import",
            "/help",
        ):
            page = client.get(path)
            assert page.status_code == 200
            assert "Local UI only. Not a remote admin console." in page.text

        doc = client.get("/docs/zh/GUI_GUIDE.md")
        assert doc.status_code == 200
        assert "不做裸盘恢复" in doc.text

        guide = client.get("/docs/USER_GUIDE_ZH.md")
        assert guide.status_code == 200
        assert "SafeVault 用户指南" in guide.text

        help_page = client.get("/help")
        assert "安装与首次设置" in help_page.text
        assert "/docs/FAQ_ZH.md" in help_page.text
        assert "USER_MANUAL.md" not in help_page.text


def test_favicon_is_intentionally_empty_instead_of_404(sv_home: Path) -> None:
    with TestClient(create_app(token=TOKEN)) as client:
        response = client.get("/favicon.ico")

    assert response.status_code == 204


def test_ui_post_requires_token(sv_home: Path, project: Path) -> None:
    with TestClient(create_app(token=TOKEN)) as client:
        response = client.post(
            "/roots/add",
            data={"path": str(project), "profile": "coding"},
        )
    assert response.status_code == 403


def test_ui_can_add_root_and_run_snapshot(sv_home: Path, project: Path) -> None:
    (project / "tracked.txt").write_text("tracked", encoding="utf-8")

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/roots/add",
            data={"path": str(project), "profile": "coding"},
        )
        assert response.status_code == 200
        assert "Protected root" in response.text

        root_id = _root_id_for(project)
        response = client.post(
            f"/roots/{root_id}/snapshot",
            data={"reason": "ui-test"},
        )
        assert response.status_code == 200
        assert "Snapshot" in response.text
        assert _version_count() == 1


def test_ui_can_stop_automatic_protection_without_deleting_history(
    sv_home: Path, project: Path
) -> None:
    (project / "tracked.txt").write_text("tracked", encoding="utf-8")
    add_protected_root(project, "coding")
    create_snapshot(project, reason="before-disable")
    root_id = _root_id_for(project)
    versions_before = _version_count()

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(f"/roots/{root_id}/disable")

    assert response.status_code == 200
    assert "已有恢复点和历史版本仍然保留" in response.text
    assert _version_count() == versions_before
    conn = connect()
    try:
        policy = conn.execute(
            "SELECT enabled FROM protection_policies WHERE root_id = ?", (root_id,)
        ).fetchone()
    finally:
        conn.close()
    assert policy is not None
    assert int(policy["enabled"]) == 0


def test_ui_labels_destructive_unprotect_as_history_removal(
    sv_home: Path, project: Path
) -> None:
    add_protected_root(project, "coding")
    root_id = _root_id_for(project)

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.get(f"/roots/{root_id}")

    assert response.status_code == 200
    assert "彻底移除历史记录" in response.text
    assert "之后无法再通过 SafeVault 恢复" in response.text


def test_ui_can_preview_and_confirm_history_removal_without_typing_id(
    sv_home: Path, project: Path
) -> None:
    (project / "tracked.txt").write_text("tracked", encoding="utf-8")
    add_protected_root(project, "coding")
    create_snapshot(project, reason="before-unprotect")
    root_id = _root_id_for(project)

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        preview = client.post(
            f"/roots/{root_id}/unprotect", data={"mode": "dry-run"}
        )
        assert preview.status_code == 200
        assert "确认删除全部历史" in preview.text
        assert 'name="confirmation"' in preview.text

        removed = client.post(
            f"/roots/{root_id}/unprotect",
            data={"mode": "confirm", "confirmation": str(root_id)},
        )

    assert removed.status_code == 200
    assert "目录及历史索引已移除" in removed.text
    assert project.is_dir()
    assert (project / "tracked.txt").read_text(encoding="utf-8") == "tracked"
    assert _root_count() == 0


def test_unprotect_database_error_is_reported_without_partial_delete(
    sv_home: Path, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_protected_root(project, "coding")
    root_id = _root_id_for(project)

    def broken_connect() -> sqlite3.Connection:
        return sqlite3.connect(":memory:")

    monkeypatch.setattr("safevault.ui.services.connect", broken_connect)
    monkeypatch.setattr(
        "safevault.ui.services.plan_unprotect_from_ui",
        lambda _root_id: {"root_id": root_id, "root_path": str(project.resolve())},
    )

    with pytest.raises(SafeVaultError, match="删除历史失败，未删除任何数据"):
        unprotect_from_ui(root_id, str(root_id))


def test_ui_lists_and_deletes_only_managed_external_backups(
    sv_home: Path, tmp_path: Path
) -> None:
    target = tmp_path / "backups"
    target.mkdir()
    backup = target / "safevault-backup-20260713-120000-123456.tar.gz"
    backup.write_bytes(b"backup")
    latest = target / "safevault-latest.tar.gz"
    latest.write_bytes(b"latest")
    unrelated = target / "notes.txt"
    unrelated.write_text("keep", encoding="utf-8")
    outside = tmp_path / "outside.tar.gz"
    outside.write_bytes(b"outside")
    save_config(
        SafeVaultConfig(
            backup=BackupConfig(enabled=True, target=str(target), schedule="daily")
        )
    )

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        page = client.get("/export-import")
        assert backup.name in page.text
        assert latest.name in page.text
        assert unrelated.name not in page.text

        rejected = client.post(
            "/backup/delete",
            data={"filename": "../outside.tar.gz", "confirmed": "true"},
        )
        assert "不是可由 SafeVault 管理的备份文件" in rejected.text
        assert outside.is_file()

        deleted = client.post(
            "/backup/delete",
            data={"filename": backup.name, "confirmed": "true"},
        )

    assert deleted.status_code == 200
    assert "已删除备份文件" in deleted.text
    assert not backup.exists()
    assert latest.is_file()
    assert unrelated.is_file()


def test_ui_add_root_rejects_safevault_home(sv_home: Path) -> None:
    sv_home.mkdir(parents=True)

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/roots/add",
            data={"path": str(sv_home), "profile": "coding"},
        )

    assert response.status_code == 200
    assert "SAFEVAULT_HOME" in response.text


def test_ui_add_root_rejects_filesystem_root(sv_home: Path, tmp_path: Path) -> None:
    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/roots/add",
            data={"path": tmp_path.anchor, "profile": "coding"},
        )

    assert response.status_code == 200
    assert "filesystem root" in response.text


def test_ui_add_root_rejects_backup_target(
    sv_home: Path, project: Path, tmp_path: Path
) -> None:
    backup_target = tmp_path / "backup-target"
    backup_target.mkdir()
    save_config(
        SafeVaultConfig(
            backup=BackupConfig(enabled=True, target=str(backup_target))
        )
    )

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/roots/add",
            data={"path": str(backup_target), "profile": "coding"},
        )

    assert response.status_code == 200
    assert "backup target" in response.text


def test_ui_add_root_rejects_duplicate_with_clear_message(
    sv_home: Path, project: Path
) -> None:
    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        first = client.post(
            "/roots/add",
            data={"path": str(project), "profile": "coding"},
        )
        second = client.post(
            "/roots/add",
            data={"path": str(project), "profile": "coding"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert "already protected" in second.text


def test_ui_add_root_reenables_disabled_root(sv_home: Path, project: Path) -> None:
    add_protected_root(project, "coding")
    remove_protected_root(project)

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/roots/add",
            data={"path": str(project), "profile": "documents"},
        )

    assert response.status_code == 200
    conn = connect()
    try:
        row = conn.execute(
            """
            SELECT p.enabled, p.watch_enabled, p.paused_until, p.profile
            FROM protection_policies p
            JOIN roots r ON r.id = p.root_id
            WHERE r.path = ?
            """,
            (str(project.resolve()),),
        ).fetchone()
    finally:
        conn.close()
    assert row["enabled"] == 1
    assert row["watch_enabled"] == 1
    assert row["paused_until"] is None
    assert row["profile"] == "documents"


def test_onboarding_backup_target_inside_selected_root_is_rejected(
    sv_home: Path, project: Path
) -> None:
    backup_target = project / "backups"

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/onboarding",
            data={
                "roots": str(project),
                "backup_target": str(backup_target),
                "backup_schedule": "daily",
            },
        )

    assert response.status_code == 200
    assert "backup target must not be inside a protected root" in response.text
    assert not backup_target.exists()
    assert _root_count() == 0
    assert not load_config().app.onboarding_completed


def test_onboarding_selected_root_inside_safevault_home_is_rejected(
    sv_home: Path,
) -> None:
    sv_home.mkdir(parents=True, exist_ok=True)

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        response = client.post(
            "/onboarding",
            data={
                "roots": str(sv_home),
                "backup_target": "",
                "backup_schedule": "daily",
            },
        )

    assert response.status_code == 200
    assert "SAFEVAULT_HOME" in response.text
    assert _root_count() == 0
    assert not load_config().app.onboarding_completed


def test_ui_versions_restore_and_deleted_page(sv_home: Path, project: Path) -> None:
    file_path = project / "note.txt"
    file_path.write_text("first", encoding="utf-8")
    create_snapshot(project, reason="first")
    file_path.write_text("second", encoding="utf-8")
    create_snapshot(project, reason="second")
    file_path.unlink()
    create_snapshot(project, reason="deleted")
    conn = connect()
    try:
        first_version = conn.execute(
            """
            SELECT id FROM versions
            WHERE rel_path = 'note.txt' AND is_deleted_marker = 0
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    assert first_version is not None

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        deleted = client.get("/deleted", params={"since": "7d"})
        assert deleted.status_code == 200
        assert "note.txt" in deleted.text

        versions = client.get("/versions", params={"file": str(file_path)})
        assert versions.status_code == 200
        assert "恢复中心" in versions.text
        assert "恢复点" in versions.text
        assert "note.txt" in versions.text
        assert "Hash" not in versions.text
        assert "<th>Version</th>" not in versions.text

        restored = client.post(
            "/restore",
            data={"file": str(file_path), "mode": "latest", "confirmation": "CONFIRM"},
        )
        assert restored.status_code == 200
        assert "Restored to" in restored.text
        assert file_path.read_text(encoding="utf-8") == "second"

        old_copy = project / "note-first.txt"
        restored_old = client.post(
            "/restore",
            data={
                "file": str(file_path),
                "mode": "version",
                "version_id": str(first_version["id"]),
                "to_path": str(old_copy),
                "confirmation": "CONFIRM",
            },
        )
        assert restored_old.status_code == 200
        assert old_copy.read_text(encoding="utf-8") == "first"


def test_ui_sandbox_dry_run_preserves_project(sv_home: Path, project: Path) -> None:
    old_file = project / "old.txt"
    new_file = project / "new.txt"
    old_file.write_text("old", encoding="utf-8")
    command = (
        "from pathlib import Path; "
        "Path('old.txt').unlink(); "
        "Path('new.txt').write_text('new', encoding='utf-8')"
    )
    sandbox_id, returncode, _diff, _diff_path = create_sandbox(
        project, [sys.executable, "-c", command]
    )
    assert returncode == 0

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        detail = client.get(f"/sandboxes/{sandbox_id}")
        assert detail.status_code == 200
        assert sandbox_id in detail.text

        rejected = client.post(
            f"/sandboxes/{sandbox_id}/apply",
            data={
                "dry_run": "true",
                "allow_delete": "true",
                "delete_confirmation": "wrong",
            },
        )
        assert rejected.status_code == 200
        assert "ALLOW DELETE" in rejected.text

        result = client.post(
            f"/sandboxes/{sandbox_id}/apply",
            data={
                "dry_run": "true",
                "allow_delete": "true",
                "delete_confirmation": "ALLOW DELETE",
            },
        )
        assert result.status_code == 200
        assert "Apply Result" in result.text

    assert old_file.read_text(encoding="utf-8") == "old"
    assert not new_file.exists()
    assert _sandbox_status(sandbox_id) == "complete"


def test_ui_maintenance_actions(sv_home: Path) -> None:
    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        doctor = client.post("/maintenance", data={"action": "doctor-fast"})
        assert doctor.status_code == 200
        assert "doctor-fast complete" in doctor.text

        verify = client.post("/maintenance", data={"action": "verify-fast"})
        assert verify.status_code == 200
        assert "verify-fast complete" in verify.text

        prune = client.post(
            "/maintenance",
            data={"action": "prune-confirm", "confirmation": "wrong"},
        )
        assert prune.status_code == 200
        assert "type PRUNE" in prune.text


def test_ui_export_import_dry_run_and_export_guard(
    sv_home: Path, project: Path, tmp_path: Path
) -> None:
    (project / "tracked.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = tmp_path / "safevault-export.tar"

    with TestClient(create_app(token=TOKEN)) as client:
        client.get("/", params={"token": TOKEN})
        exported = client.post(
            "/export-import/export",
            data={"output": str(output)},
        )
        assert exported.status_code == 200
        assert "Exported" in exported.text
        assert output.is_file()

        guarded = client.post(
            "/export-import/export",
            data={"output": str(sv_home / "inside.tar")},
        )
        assert guarded.status_code == 200
        assert "SAFEVAULT_HOME" in guarded.text

        target_home = tmp_path / "imported-safevault-home"
        imported = client.post(
            "/export-import/import",
            data={
                "input_path": str(output),
                "target_home": str(target_home),
                "dry_run": "true",
            },
        )
        assert imported.status_code == 200
        assert "dry-run" in imported.text
        assert not target_home.exists()
