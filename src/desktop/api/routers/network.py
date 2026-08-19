"""LAN login and session endpoints."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import RLock

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from src.desktop import network_access


router = APIRouter(prefix="/api/network", tags=["network"])

_attempt_lock = RLock()
_login_attempts: dict[str, deque[float]] = defaultdict(deque)
_ATTEMPT_WINDOW_SECONDS = 60.0
_MAX_ATTEMPTS = 5


class LoginRequest(BaseModel):
    access_token: str


def _remote_access_required(request: Request) -> bool:
    return network_access.is_lan_access_active() and not network_access.is_loopback_host(
        network_access.client_host(request.scope)
    )


def _check_login_rate_limit(host: str) -> None:
    now = time.monotonic()
    cutoff = now - _ATTEMPT_WINDOW_SECONDS
    with _attempt_lock:
        attempts = _login_attempts[host]
        while attempts and attempts[0] < cutoff:
            attempts.popleft()
        if len(attempts) >= _MAX_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Too many login attempts")
        attempts.append(now)


def _clear_login_attempts(host: str) -> None:
    with _attempt_lock:
        _login_attempts.pop(host, None)


@router.get("/session")
async def get_session(request: Request):
    required = _remote_access_required(request)
    token_hash = network_access.load_network_settings()["token_hash"]
    authenticated = not required or network_access.scope_has_valid_session(
        request.scope, token_hash
    )
    return {
        "required": required,
        "authenticated": authenticated,
        "host": network_access.client_host(request.scope),
    }


@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response):
    if not _remote_access_required(request):
        return {"success": True, "authenticated": True}

    host = network_access.client_host(request.scope)
    _check_login_rate_limit(host)
    token_hash = network_access.load_network_settings()["token_hash"]
    if not network_access.verify_access_token(payload.access_token, token_hash):
        raise HTTPException(status_code=401, detail="Access token is invalid")

    _clear_login_attempts(host)
    response.set_cookie(
        key=network_access.SESSION_COOKIE,
        value=network_access.session_cookie_value(token_hash),
        max_age=network_access.SESSION_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"success": True, "authenticated": True}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(network_access.SESSION_COOKIE, path="/")
    return {"success": True}
