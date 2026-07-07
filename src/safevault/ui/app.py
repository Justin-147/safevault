from __future__ import annotations

import secrets
from importlib.resources import files

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from safevault.ui.routes import build_router


def create_app(token: str | None = None) -> FastAPI:
    ui_token = token or secrets.token_urlsafe(32)
    app = FastAPI(title="SafeVault Local UI")
    app.state.safevault_ui_token = ui_token
    package_files = files("safevault.ui")
    static_dir = package_files.joinpath("static")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    app.include_router(build_router())
    return app

