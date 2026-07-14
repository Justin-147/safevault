from __future__ import annotations

import secrets
from importlib.resources import files

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from safevault.ui.auth import require_token
from safevault.ui.routes import build_router


def create_app(token: str | None = None) -> FastAPI:
    ui_token = token or secrets.token_urlsafe(32)
    app = FastAPI(title="SafeVault Local UI")
    app.state.safevault_ui_token = ui_token
    package_files = files("safevault.ui")
    static_dir = package_files.joinpath("static")
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/health", include_in_schema=False)
    async def health(request: Request, response: Response) -> dict[str, str]:
        # Keep tray readiness checks off the database-heavy dashboard route.
        require_token(request, response)
        return {"status": "ok"}

    app.include_router(build_router())
    return app
