from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from safevault.config import load_config
from safevault.db import connect
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
        with TestClient(create_app(token=token)) as client:
            first = client.get("/", params={"token": token})
            assert first.status_code == 200
            assert "欢迎使用 SafeVault" in first.text
            completed = client.post(
                "/onboarding",
                data={"roots": str(desktop), "backup_schedule": "manual"},
            )
            assert completed.status_code == 200
            assert "Onboarding complete" in completed.text
        config = load_config()
        assert config.app.onboarding_completed is True
        conn = connect()
        try:
            snapshots = int(
                conn.execute(
                    "SELECT COUNT(*) FROM snapshots WHERE reason = 'onboarding-initial'"
                ).fetchone()[0]
            )
        finally:
            conn.close()
        assert snapshots == 1
    print("onboarding smoke ok")


if __name__ == "__main__":
    main()
