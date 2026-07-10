from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from safevault.config import load_config
from safevault.daemon import run_daemon
from safevault.db import connect
from safevault.ui import services
from safevault.ui.app import create_app


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="safevault-onboarding-smoke-") as tmp:
        base = Path(tmp)
        safevault_home = base / "home"
        user_home = base / "user"
        desktop = user_home / "Desktop"
        desktop.mkdir(parents=True)
        (desktop / "smoke.txt").write_text("hello", encoding="utf-8")
        os.environ["SAFEVAULT_HOME"] = str(safevault_home)
        os.environ["USERPROFILE"] = str(user_home)
        token = "smoke-token"
        daemon_requests: list[str] = []
        original_ensure_daemon = services.ensure_daemon_running
        services.ensure_daemon_running = lambda: daemon_requests.append("start") or True
        try:
            with TestClient(create_app(token=token)) as client:
                first = client.get("/", params={"token": token})
                assert first.status_code == 200
                assert "欢迎使用 SafeVault" in first.text
                completed = client.post(
                    "/onboarding",
                    data={"roots": str(desktop), "backup_schedule": "manual"},
                )
                assert completed.status_code == 200
                assert "设置完成" in completed.text
                assert "初始扫描正在后台进行" in completed.text
        finally:
            services.ensure_daemon_running = original_ensure_daemon
        assert daemon_requests == ["start"]
        config = load_config()
        assert config.app.onboarding_completed is True
        conn = connect()
        try:
            synchronous_snapshots = int(
                conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            )
        finally:
            conn.close()
        assert synchronous_snapshots == 0

        run_daemon(test_once=True)
        conn = connect()
        try:
            background_snapshots = int(
                conn.execute(
                    "SELECT COUNT(*) FROM snapshots WHERE reason = 'pre-daemon-start'"
                ).fetchone()[0]
            )
        finally:
            conn.close()
        assert background_snapshots == 1
    print("onboarding smoke ok")


if __name__ == "__main__":
    main()
