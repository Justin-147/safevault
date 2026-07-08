from __future__ import annotations

import subprocess
import sys
import webbrowser
from importlib import import_module
from pathlib import Path
from typing import Any

from safevault.backup import run_backup
from safevault.daemon import get_daemon_status
from safevault.errors import SafeVaultError
from safevault.protection import list_protection, pause_protected_root, resume_protected_root
from safevault.snapshot import create_snapshot
from safevault.verify import run_verify


def tray_available() -> bool:
    try:
        _load_tray_dependencies()
    except SafeVaultError:
        return False
    return True


def run_tray(*, open_ui: bool = False, check: bool = False) -> None:
    pystray, image_mod, draw_mod = _load_tray_dependencies()
    if check:
        return
    if open_ui:
        open_safevault_ui()
    status = get_daemon_status()
    if status.status != "running":
        _spawn_safevault(["daemon", "run"])
    icon = pystray.Icon(
        "SafeVault",
        _build_icon(image_mod, draw_mod),
        "SafeVault",
        menu=pystray.Menu(
            pystray.MenuItem("Open SafeVault", lambda _icon, _item: open_safevault_ui()),
            pystray.MenuItem("Recent Deleted", lambda _icon, _item: open_safevault_ui()),
            pystray.MenuItem("Run Snapshot Now", lambda _icon, _item: snapshot_all_roots()),
            pystray.MenuItem("Run Verify", lambda _icon, _item: run_verify(deep=False)),
            pystray.MenuItem("Backup Now", lambda _icon, _item: run_backup()),
            pystray.MenuItem(
                "Pause Protection 30 min",
                lambda _icon, _item: pause_all_roots("30m"),
            ),
            pystray.MenuItem("Resume Protection", lambda _icon, _item: resume_all_roots()),
            pystray.MenuItem("Quit", lambda icon, _item: icon.stop()),
        ),
    )
    icon.run()


def open_safevault_ui() -> None:
    _spawn_safevault(["ui", "--open"])
    webbrowser.open("http://127.0.0.1:8765")


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


def _spawn_safevault(args: list[str]) -> None:
    kwargs: dict[str, Any] = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    subprocess.Popen([sys.executable, "-m", "safevault", *args], **kwargs)


def _load_tray_dependencies():
    try:
        pystray = import_module("pystray")
        image_mod = import_module("PIL.Image")
        draw_mod = import_module("PIL.ImageDraw")
    except ModuleNotFoundError as exc:
        raise SafeVaultError("Install tray dependencies with: pip install -e '.[tray]'") from exc
    return pystray, image_mod, draw_mod


def _build_icon(image_mod, draw_mod):
    image = image_mod.new("RGB", (64, 64), "#0969da")
    draw = draw_mod.Draw(image)
    draw.rectangle((14, 26, 50, 52), fill="#ffffff")
    draw.arc((18, 10, 46, 42), start=180, end=360, fill="#ffffff", width=6)
    draw.rectangle((26, 34, 38, 46), fill="#0969da")
    return image
