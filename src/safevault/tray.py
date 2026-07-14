from __future__ import annotations

import os
import sys
import time
import webbrowser
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path

from safevault.backup import run_backup
from safevault.daemon import get_daemon_status, request_daemon_stop
from safevault.errors import SafeVaultError
from safevault.processes import spawn_safevault
from safevault.protection import list_protection, pause_protected_root, resume_protected_root
from safevault.snapshot import create_snapshot
from safevault.ui.session import (
    find_available_ui_port,
    read_ui_session,
    request_ui_stop,
    ui_session_reachable,
    ui_url,
)
from safevault.verify import run_verify


def tray_available() -> bool:
    try:
        _check_tray_dependencies()
    except SafeVaultError:
        return False
    return True


def run_tray(*, open_ui: bool = False, check: bool = False) -> None:
    if check:
        _check_tray_dependencies()
        return
    pystray, image_mod, draw_mod = _load_tray_dependencies()
    if open_ui:
        open_safevault_ui()
    status = get_daemon_status()
    if status.status != "running" and not status.lock_exists:
        _spawn_safevault(["daemon", "run"])
    icon = pystray.Icon(
        "SafeVault",
        _build_icon(image_mod, draw_mod),
        "SafeVault",
        menu=pystray.Menu(
            pystray.MenuItem("Open SafeVault", lambda _icon, _item: open_safevault_ui()),
            pystray.MenuItem(
                "Recent Deleted",
                lambda _icon, _item: open_safevault_ui(path="/deleted"),
            ),
            pystray.MenuItem("Run Snapshot Now", lambda _icon, _item: snapshot_all_roots()),
            pystray.MenuItem("Run Verify", lambda _icon, _item: run_verify(deep=False)),
            pystray.MenuItem("Backup Now", lambda _icon, _item: run_backup()),
            pystray.MenuItem(
                "Pause Protection 30 min",
                lambda _icon, _item: pause_all_roots("30m"),
            ),
            pystray.MenuItem("Resume Protection", lambda _icon, _item: resume_all_roots()),
            pystray.MenuItem("Quit SafeVault", lambda icon, _item: quit_safevault(icon)),
        ),
    )
    icon.run()


def open_safevault_ui(*, path: str = "/") -> None:
    session = read_ui_session()
    if session is not None and ui_session_reachable(session):
        _open_browser_url(ui_url(session, path=path))
        return
    port = find_available_ui_port()
    _spawn_safevault(["ui", "--port", str(port)])
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        session = read_ui_session()
        if session is not None:
            url = ui_url(session, path=path)
            if ui_session_reachable(session, timeout=0.5):
                _open_browser_url(url)
                return
        time.sleep(0.2)
    raise SafeVaultError("SafeVault UI session did not become available")


def _open_browser_url(url: str) -> None:
    opened = webbrowser.open(url)
    if opened is not False:
        return
    startfile = getattr(os, "startfile", None)
    if sys.platform.startswith("win") and callable(startfile):
        try:
            startfile(url)
            return
        except OSError as exc:
            raise SafeVaultError("Could not open the SafeVault UI in a browser") from exc
    raise SafeVaultError("Could not open the SafeVault UI in a browser")


def snapshot_all_roots() -> None:
    for policy in list_protection():
        if policy.enabled:
            create_snapshot(Path(policy.root_path), reason="tray-manual")


def pause_all_roots(duration: str) -> None:
    for policy in list_protection():
        if policy.enabled:
            pause_protected_root(Path(policy.root_path), duration)


def resume_all_roots() -> None:
    for policy in list_protection():
        if policy.enabled:
            resume_protected_root(Path(policy.root_path))


def quit_safevault(icon) -> None:
    """Stop background protection and close the tray for the current session."""

    request_daemon_stop()
    request_ui_stop()
    icon.stop()


def _spawn_safevault(args: list[str]) -> None:
    log_name = "ui" if args and args[0] == "ui" else "daemon"
    spawn_safevault(args, log_name=log_name)


def _load_tray_dependencies():
    try:
        pystray = import_module("pystray")
        image_mod = import_module("PIL.Image")
        draw_mod = import_module("PIL.ImageDraw")
    except ModuleNotFoundError as exc:
        raise SafeVaultError("Install tray dependencies with: pip install -e '.[tray]'") from exc
    return pystray, image_mod, draw_mod


def _check_tray_dependencies() -> None:
    missing = [
        module
        for module in ("pystray", "PIL.Image", "PIL.ImageDraw")
        if _module_missing(module)
    ]
    if missing:
        raise SafeVaultError(
            "Install tray dependencies with: pip install -e '.[tray]' "
            f"(missing: {', '.join(missing)})"
        )


def _module_missing(module: str) -> bool:
    try:
        return find_spec(module) is None
    except ModuleNotFoundError:
        return True


def _build_icon(image_mod, draw_mod):
    image = image_mod.new("RGB", (64, 64), "#0969da")
    draw = draw_mod.Draw(image)
    draw.rectangle((14, 26, 50, 52), fill="#ffffff")
    draw.arc((18, 10, 46, 42), start=180, end=360, fill="#ffffff", width=6)
    draw.rectangle((26, 34, 38, 46), fill="#0969da")
    return image
