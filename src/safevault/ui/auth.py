from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, Response, status

UI_COOKIE_NAME = "safevault_ui_token"


def _candidate_token(request: Request) -> str | None:
    query_token = request.query_params.get("token")
    if query_token:
        return query_token
    header_token = request.headers.get("X-SafeVault-Token")
    if header_token:
        return header_token
    cookie_token = request.cookies.get(UI_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return None


def require_token(request: Request, response: Response) -> str:
    expected = str(request.app.state.safevault_ui_token)
    supplied = _candidate_token(request)
    if supplied is None or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SafeVault UI token required",
        )
    if request.query_params.get("token") == expected:
        response.set_cookie(
            UI_COOKIE_NAME,
            expected,
            httponly=True,
            samesite="lax",
        )
    return expected

