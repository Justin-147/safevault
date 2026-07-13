from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi.testclient import TestClient

from safevault.cli import app
from safevault.db import connect, get_or_create_root
from safevault.exporter import export_vault
from safevault.paths import ensure_home_layout, get_sandboxes_dir
from safevault.snapshot import create_snapshot
from safevault.ui.app import create_app
from safevault.ui.session import UiSession, read_ui_session, ui_url

TOKEN = "test-token"


def _login(client: TestClient) -> None:
    response = client.get("/", params={"token": TOKEN})
    assert response.status_code == 200


def _post_form(client: TestClient, path: str, fields: list[tuple[str, str]]):
    return client.post(
        path,
        content=urlencode(fields),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def _prepare_deleted_file(project: Path) -> Path:
    path = project / "recover.txt"
    path.write_text("first", encoding="utf-8")
    create_snapshot(project, reason="first")
    path.write_text("second", encoding="utf-8")
    create_snapshot(project, reason="second")
    path.unlink()
    create_snapshot(project, reason="deleted")
    return path


def _make_export(project: Path, output: Path) -> Path:
    (project / "tracked.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    export_vault(output=output)
    return output


def _imported_object_count(target_home: Path) -> int:
    objects = target_home / "objects"
    if not objects.is_dir():
        return 0
    return sum(1 for path in objects.rglob("*") if path.is_file())


def _insert_old_applied_sandbox(project: Path) -> tuple[str, Path]:
    ensure_home_layout()
    sandbox_id = "old-applied-sandbox"
    sandbox_dir = get_sandboxes_dir() / sandbox_id
    sandbox_work = sandbox_dir / "work"
    sandbox_work.mkdir(parents=True)
    old_created = (datetime.now(UTC) - timedelta(days=45)).isoformat(timespec="microseconds")

    conn = connect()
    try:
        root_id = get_or_create_root(conn, project, "coding")
        conn.execute(
            """
            INSERT INTO sandboxes(id, root_id, original_path, sandbox_path, created_at, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                sandbox_id,
                root_id,
                str(project.resolve()),
                str(sandbox_work),
                old_created,
                "applied",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return sandbox_id, sandbox_dir


def test_fastapi_testclient_importable() -> None:
    from fastapi.testclient import TestClient as ImportedTestClient

    assert ImportedTestClient is TestClient


def test_ui_security_rejects_missing_tokens(sv_home: Path, project: Path) -> None:
    with TestClient(create_app(token=TOKEN)) as client:
        assert client.get("/").status_code == 403
        assert client.get("/api/dashboard/recent").status_code == 403
        assert client.get("/api/deleted").status_code == 403
        response = client.post(
            "/roots/add",
            data={"path": str(project), "profile": "coding"},
        )
        assert response.status_code == 403


def test_ui_restore_requires_confirmation(sv_home: Path, project: Path) -> None:
    file_path = _prepare_deleted_file(project)

    with TestClient(create_app(token=TOKEN)) as client:
        _login(client)
        missing = client.post("/restore", data={"file": str(file_path), "mode": "latest"})
        assert missing.status_code == 200
        assert "type RESTORE" in missing.text
        assert not file_path.exists()

        wrong = client.post(
            "/restore",
            data={"file": str(file_path), "mode": "latest", "confirmation": "wrong"},
        )
        assert wrong.status_code == 200
        assert "type RESTORE" in wrong.text
        assert not file_path.exists()


def test_ui_restore_with_confirmation_succeeds(sv_home: Path, project: Path) -> None:
    file_path = _prepare_deleted_file(project)

    with TestClient(create_app(token=TOKEN)) as client:
        _login(client)
        restored = client.post(
            "/restore",
            data={"file": str(file_path), "mode": "latest", "confirmation": "RESTORE"},
        )
        assert restored.status_code == 200
        assert "Restored to" in restored.text

    assert file_path.read_text(encoding="utf-8") == "second"


def test_ui_maintenance_confirmations(sv_home: Path, project: Path) -> None:
    _sandbox_id, sandbox_dir = _insert_old_applied_sandbox(project)

    with TestClient(create_app(token=TOKEN)) as client:
        _login(client)
        prune = client.post("/maintenance", data={"action": "prune-confirm"})
        assert prune.status_code == 200
        assert "type PRUNE" in prune.text

        missing = client.post(
            "/maintenance",
            data={"action": "sandbox-clean-confirm"},
        )
        assert missing.status_code == 200
        assert "type CLEAN SANDBOXES" in missing.text
        assert sandbox_dir.exists()

        wrong = client.post(
            "/maintenance",
            data={"action": "sandbox-clean-confirm", "confirmation": "wrong"},
        )
        assert wrong.status_code == 200
        assert "type CLEAN SANDBOXES" in wrong.text
        assert sandbox_dir.exists()

        cleaned = client.post(
            "/maintenance",
            data={
                "action": "sandbox-clean-confirm",
                "confirmation": "CLEAN SANDBOXES",
            },
        )
        assert cleaned.status_code == 200
        assert "sandbox-clean-confirm complete" in cleaned.text
        assert not sandbox_dir.exists()


def test_ui_export_high_risk_options_require_confirmation(
    sv_home: Path, project: Path, tmp_path: Path
) -> None:
    (project / "tracked.txt").write_text("tracked", encoding="utf-8")
    create_snapshot(project)
    output = tmp_path / "safevault-export.tar"
    output.write_text("existing", encoding="utf-8")

    with TestClient(create_app(token=TOKEN)) as client:
        _login(client)
        overwrite_missing = client.post(
            "/export-import/export",
            data={"output": str(output), "overwrite": "true"},
        )
        assert overwrite_missing.status_code == 200
        assert "type OVERWRITE EXPORT" in overwrite_missing.text
        assert output.read_text(encoding="utf-8") == "existing"

        skip_missing = client.post(
            "/export-import/export",
            data={"output": str(tmp_path / "skip.tar"), "skip_verify": "true"},
        )
        assert skip_missing.status_code == 200
        assert "type SKIP VERIFY" in skip_missing.text
        assert not (tmp_path / "skip.tar").exists()

        overwrite_ok = client.post(
            "/export-import/export",
            data={
                "output": str(output),
                "overwrite": "true",
                "overwrite_confirmation": "OVERWRITE EXPORT",
            },
        )
        assert overwrite_ok.status_code == 200
        assert "Exported" in overwrite_ok.text

        skip_ok = client.post(
            "/export-import/export",
            data={
                "output": str(tmp_path / "skip.tar"),
                "skip_verify": "true",
                "skip_verify_confirmation": "SKIP VERIFY",
            },
        )
        assert skip_ok.status_code == 200
        assert "Exported" in skip_ok.text
        assert (tmp_path / "skip.tar").is_file()


def test_ui_import_confirmations_and_dry_run(
    sv_home: Path, project: Path, tmp_path: Path
) -> None:
    archive = _make_export(project, tmp_path / "safevault-export.tar")

    with TestClient(create_app(token=TOKEN)) as client:
        _login(client)
        target = tmp_path / "import-target"
        missing_import = client.post(
            "/export-import/import",
            data={
                "input_path": str(archive),
                "target_home": str(target),
                "dry_run": "false",
                "confirm": "true",
            },
        )
        assert missing_import.status_code == 200
        assert "type IMPORT" in missing_import.text
        assert not target.exists()

        missing_overwrite = client.post(
            "/export-import/import",
            data={
                "input_path": str(archive),
                "target_home": str(target),
                "dry_run": "false",
                "confirm": "true",
                "import_confirmation": "IMPORT",
                "overwrite": "true",
            },
        )
        assert missing_overwrite.status_code == 200
        assert "type OVERWRITE" in missing_overwrite.text
        assert not target.exists()

        dry_run = client.post(
            "/export-import/import",
            data={
                "input_path": str(archive),
                "target_home": str(target),
                "dry_run": "true",
                "confirm": "true",
                "import_confirmation": "IMPORT",
            },
        )
        assert dry_run.status_code == 200
        assert "dry-run" in dry_run.text
        assert not target.exists()


def test_ui_import_default_form_remains_dry_run(
    sv_home: Path, project: Path, tmp_path: Path
) -> None:
    archive = _make_export(project, tmp_path / "safevault-export.tar")
    target = tmp_path / "default-dry-run-target"

    with TestClient(create_app(token=TOKEN)) as client:
        _login(client)
        response = _post_form(
            client,
            "/export-import/import",
            [
                ("input_path", str(archive)),
                ("target_home", str(target)),
                ("dry_run", "false"),
                ("dry_run", "true"),
                ("confirm", "false"),
            ],
        )
        assert response.status_code == 200
        assert "dry-run" in response.text
        assert not target.exists()


def test_ui_import_confirm_real_browser_unchecked_dry_run_imports(
    sv_home: Path, project: Path, tmp_path: Path
) -> None:
    archive = _make_export(project, tmp_path / "safevault-export.tar")
    target = tmp_path / "imported-home"

    with TestClient(create_app(token=TOKEN)) as client:
        _login(client)
        response = _post_form(
            client,
            "/export-import/import",
            [
                ("input_path", str(archive)),
                ("target_home", str(target)),
                ("dry_run", "false"),
                ("confirm", "false"),
                ("confirm", "true"),
                ("import_confirmation", "IMPORT"),
                ("overwrite", "false"),
            ],
        )
        assert response.status_code == 200
        assert "complete" in response.text

    assert (target / "vault.db").is_file()
    assert _imported_object_count(target) >= 1


def test_cli_ui_host_security_and_test_token(
    runner, sv_home: Path, monkeypatch
) -> None:
    public = runner.invoke(app, ["ui", "--host", "0.0.0.0"])
    assert public.exit_code == 1
    assert "--allow-public-bind" in public.output

    import uvicorn

    calls: dict[str, object] = {}

    def fake_run(app_obj, host: str, port: int) -> None:
        session = read_ui_session()
        assert session is not None
        calls["host"] = host
        calls["port"] = port
        calls["token"] = app_obj.state.safevault_ui_token
        calls["url"] = ui_url(session)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    local = runner.invoke(
        app,
        [
            "ui",
            "--host",
            "127.0.0.1",
            "--port",
            "9876",
            "--test-token",
            "known-test-token",
        ],
    )
    assert local.exit_code == 0
    assert "known-test-token" in local.output
    assert calls == {
        "host": "127.0.0.1",
        "port": 9876,
        "token": "known-test-token",
        "url": "http://127.0.0.1:9876/?token=known-test-token",
    }


def test_ui_command_removes_session_after_shutdown(runner, sv_home: Path, monkeypatch) -> None:
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app_obj, host, port: None)

    result = runner.invoke(app, ["ui", "--test-token", "session-token"])

    assert result.exit_code == 0
    assert read_ui_session() is None


def test_ui_command_reuses_existing_reachable_session(
    runner, sv_home: Path, monkeypatch
) -> None:
    session = UiSession(
        host="127.0.0.1",
        port=8765,
        token="existing-token",
        started_at="2026-07-10T00:00:00+00:00",
        pid=123,
    )
    opened = []
    monkeypatch.setattr("safevault.ui.session.read_ui_session", lambda: session)
    monkeypatch.setattr("safevault.ui.session.ui_session_reachable", lambda item: True)
    monkeypatch.setattr("safevault.cli.webbrowser.open", opened.append)

    result = runner.invoke(app, ["ui", "--open"])

    assert result.exit_code == 0
    assert "already running" in result.output
    assert opened == ["http://127.0.0.1:8765/?token=existing-token"]


def test_ui_command_can_open_storage_in_existing_session(
    runner, sv_home: Path, monkeypatch
) -> None:
    session = UiSession(
        host="127.0.0.1",
        port=8765,
        token="existing-token",
        started_at="2026-07-10T00:00:00+00:00",
        pid=123,
    )
    opened = []
    monkeypatch.setattr("safevault.ui.session.read_ui_session", lambda: session)
    monkeypatch.setattr("safevault.ui.session.ui_session_reachable", lambda item: True)
    monkeypatch.setattr("safevault.cli.webbrowser.open", opened.append)

    result = runner.invoke(app, ["ui", "--open", "--page", "storage"])

    assert result.exit_code == 0
    assert opened == ["http://127.0.0.1:8765/storage?token=existing-token"]
