"""Optional HTTP basic auth.

Off by default so local development is frictionless. Set TF_AUTH_USER and
TF_AUTH_PASS and every route needs credentials - which matters the moment this
is on a public URL, because an unauthenticated visitor can spend your
API-Football quota (and `POST /api/transfers/sync` costs 110 calls a go).
"""
from __future__ import annotations

import base64
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from .config import settings

# Left open so platform health checks work without credentials.
_OPEN_PATHS = {"/api/health"}


def _unauthorised() -> Response:
    return JSONResponse(
        {"detail": "authentication required"},
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="TotalFootball", charset="UTF-8"'},
    )


async def basic_auth_middleware(request: Request, call_next):
    if not settings.auth_enabled or request.url.path in _OPEN_PATHS:
        return await call_next(request)

    header = request.headers.get("Authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return _unauthorised()
    try:
        user, _, password = base64.b64decode(encoded).decode("utf-8").partition(":")
    except (ValueError, UnicodeDecodeError):
        return _unauthorised()

    # compare_digest on both halves, so timing does not leak which one is wrong
    ok_user = secrets.compare_digest(user, settings.auth_user)
    ok_pass = secrets.compare_digest(password, settings.auth_pass)
    if not (ok_user and ok_pass):
        return _unauthorised()

    return await call_next(request)
