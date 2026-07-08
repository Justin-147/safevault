from __future__ import annotations

from safevault.cli import app
from safevault.tray import open_safevault_ui, tray_available
from safevault.ui.session import UiSession


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
    monkeypatch.setattr("safevault.tray.time.sleep", lambda seconds: None)

    open_safevault_ui()

    assert spawned == [["ui"]]
    assert opened == ["http://127.0.0.1:8765/?token=fresh"]
