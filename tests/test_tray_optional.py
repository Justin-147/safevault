from __future__ import annotations

from safevault.cli import app
from safevault.tray import open_safevault_ui, quit_safevault, tray_available
from safevault.ui.session import UiSession, ui_session_reachable


def test_tray_check_is_safe_when_optional_dependencies_are_missing(runner, sv_home) -> None:
    result = runner.invoke(app, ["tray", "--check"])

    if tray_available():
        assert result.exit_code == 0
        assert "tray dependencies available" in result.output
    else:
        assert result.exit_code != 0
        assert "Install tray dependencies" in result.output


def test_tray_open_ui_uses_token_url(monkeypatch, sv_home) -> None:
    opened = []
    session = UiSession(
        host="127.0.0.1",
        port=8765,
        token="abc",
        started_at="2026-07-08T00:00:00+00:00",
        pid=123,
    )
    monkeypatch.setattr("safevault.tray.read_ui_session", lambda: session)
    monkeypatch.setattr("safevault.tray.ui_session_reachable", lambda item, timeout=0.5: True)
    monkeypatch.setattr("safevault.tray.webbrowser.open", opened.append)

    open_safevault_ui()

    assert opened == ["http://127.0.0.1:8765/?token=abc"]


def test_tray_recent_deleted_uses_deleted_path(monkeypatch, sv_home) -> None:
    opened = []
    session = UiSession(
        host="127.0.0.1",
        port=8765,
        token="abc",
        started_at="2026-07-08T00:00:00+00:00",
        pid=123,
    )
    monkeypatch.setattr("safevault.tray.read_ui_session", lambda: session)
    monkeypatch.setattr("safevault.tray.ui_session_reachable", lambda item, timeout=0.5: True)
    monkeypatch.setattr("safevault.tray.webbrowser.open", opened.append)

    open_safevault_ui(path="/deleted")

    assert opened == ["http://127.0.0.1:8765/deleted?token=abc"]


def test_tray_does_not_open_bare_url(monkeypatch, sv_home) -> None:
    opened = []
    session = UiSession(
        host="127.0.0.1",
        port=8765,
        token="secret",
        started_at="2026-07-08T00:00:00+00:00",
        pid=123,
    )
    monkeypatch.setattr("safevault.tray.read_ui_session", lambda: session)
    monkeypatch.setattr("safevault.tray.ui_session_reachable", lambda item, timeout=0.5: True)
    monkeypatch.setattr("safevault.tray.webbrowser.open", opened.append)

    open_safevault_ui()

    assert opened
    assert all("token=" in url for url in opened)


def test_tray_reuses_existing_ui_session_when_available(monkeypatch, sv_home) -> None:
    spawned = []
    session = UiSession("127.0.0.1", 8765, "reuse", "2026-07-08T00:00:00+00:00", 123)
    monkeypatch.setattr("safevault.tray.read_ui_session", lambda: session)
    monkeypatch.setattr("safevault.tray.ui_session_reachable", lambda item, timeout=0.5: True)
    monkeypatch.setattr("safevault.tray.webbrowser.open", lambda url: None)
    monkeypatch.setattr("safevault.tray._spawn_safevault", spawned.append)

    open_safevault_ui()

    assert spawned == []


def test_ui_session_ignores_stale_unreachable_session(monkeypatch, sv_home) -> None:
    sessions = [
        UiSession("127.0.0.1", 8765, "stale", "2026-07-08T00:00:00+00:00", 111),
        UiSession("127.0.0.1", 8765, "fresh", "2026-07-08T00:00:01+00:00", 222),
    ]
    calls = {"read": 0, "reachable": 0}
    opened = []
    spawned = []

    def fake_read():
        calls["read"] += 1
        return sessions[min(calls["read"] - 1, 1)]

    def fake_reachable(session, timeout=0.5):
        calls["reachable"] += 1
        return session.token == "fresh"

    monkeypatch.setattr("safevault.tray.read_ui_session", fake_read)
    monkeypatch.setattr("safevault.tray.ui_session_reachable", fake_reachable)
    monkeypatch.setattr("safevault.tray.webbrowser.open", opened.append)
    monkeypatch.setattr("safevault.tray._spawn_safevault", spawned.append)
    monkeypatch.setattr("safevault.tray.find_available_ui_port", lambda: 8766)
    monkeypatch.setattr("safevault.tray.time.sleep", lambda seconds: None)

    open_safevault_ui()

    assert spawned == [["ui", "--port", "8766"]]
    assert opened == ["http://127.0.0.1:8765/?token=fresh"]


def test_quit_safevault_stops_daemon_and_tray(monkeypatch, sv_home) -> None:
    calls = []

    class FakeIcon:
        def stop(self) -> None:
            calls.append("tray")

    monkeypatch.setattr("safevault.tray.request_daemon_stop", lambda: calls.append("daemon"))
    monkeypatch.setattr("safevault.tray.request_ui_stop", lambda: calls.append("ui"))

    quit_safevault(FakeIcon())

    assert calls == ["daemon", "ui", "tray"]


def test_tray_child_process_uses_shared_launcher(monkeypatch, sv_home) -> None:
    calls = []
    monkeypatch.setattr(
        "safevault.tray.spawn_safevault",
        lambda args, *, log_name: calls.append((args, log_name)),
    )

    from safevault.tray import _spawn_safevault

    _spawn_safevault(["daemon", "run"])
    _spawn_safevault(["ui"])

    assert calls == [
        (["daemon", "run"], "daemon"),
        (["ui"], "ui"),
    ]


def test_ui_reachability_uses_lightweight_health_endpoint(monkeypatch, sv_home) -> None:
    requested = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

    def fake_urlopen(url, *, timeout):
        requested.append((url, timeout))
        return FakeResponse()

    session = UiSession("127.0.0.1", 8765, "secret", "2026-07-08T00:00:00+00:00", 123)
    monkeypatch.setattr("safevault.ui.session.urllib.request.urlopen", fake_urlopen)

    assert ui_session_reachable(session, timeout=0.25) is True
    assert requested == [("http://127.0.0.1:8765/health?token=secret", 0.25)]


def test_tray_browser_open_falls_back_to_windows_default(monkeypatch, sv_home) -> None:
    opened = []
    monkeypatch.setattr("safevault.tray.webbrowser.open", lambda url: False)
    monkeypatch.setattr("safevault.tray.sys.platform", "win32")
    monkeypatch.setattr("safevault.tray.os.startfile", opened.append, raising=False)

    from safevault.tray import _open_browser_url

    _open_browser_url("http://127.0.0.1:8765/?token=secret")

    assert opened == ["http://127.0.0.1:8765/?token=secret"]
