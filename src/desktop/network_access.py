"""Opt-in LAN access configuration and authentication primitives."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
from http.cookies import SimpleCookie
from pathlib import Path
from threading import RLock
from typing import Optional

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from src.desktop.runtime import DESKTOP_CONFIG_PATH


DEFAULT_PORT = 18721
LOOPBACK_HOST = "127.0.0.1"
LAN_BIND_HOST = "0.0.0.0"
SESSION_COOKIE = "thesis_backtester_lan_session"
SESSION_MAX_AGE = 30 * 24 * 60 * 60

LAN_ENABLED_KEY = "lan_access_enabled"
LAN_TOKEN_HASH_KEY = "lan_access_token_hash"

_TOKEN_DOMAIN = b"thesis-backtester-lan-token-v1\x00"
_SESSION_DOMAIN = b"thesis-backtester-lan-session-v1"
_state_lock = RLock()
_config_path: Path = DESKTOP_CONFIG_PATH
_active_lan_access: Optional[bool] = None


def set_config_path(path: Path) -> None:
    """Use the same external desktop configuration as the settings API."""
    global _config_path
    with _state_lock:
        _config_path = Path(path)


def get_config_path() -> Path:
    with _state_lock:
        return _config_path


def load_network_settings(path: Optional[Path] = None) -> dict:
    """Read only the LAN-related fields from the desktop configuration."""
    config_path = Path(path) if path is not None else get_config_path()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
        payload = {}
    return {
        "enabled": bool(payload.get(LAN_ENABLED_KEY, False)),
        "token_hash": str(payload.get(LAN_TOKEN_HASH_KEY, "") or ""),
    }


def configure_active_lan_access(enabled: bool) -> None:
    """Freeze the effective network mode for the lifetime of this process."""
    global _active_lan_access
    with _state_lock:
        _active_lan_access = bool(enabled)


def clear_active_lan_access() -> None:
    """Return to config-driven mode. Intended for direct API use and tests."""
    global _active_lan_access
    with _state_lock:
        _active_lan_access = None


def is_lan_access_active() -> bool:
    with _state_lock:
        active = _active_lan_access
    if active is not None:
        return active
    return load_network_settings()["enabled"]


def resolve_bind_host(path: Optional[Path] = None) -> str:
    settings = load_network_settings(path)
    return LAN_BIND_HOST if settings["enabled"] else LOOPBACK_HOST


def generate_access_token() -> str:
    """Generate a high-entropy token that is still practical to copy."""
    return secrets.token_urlsafe(12)


def hash_access_token(token: str) -> str:
    normalized = str(token or "").strip().encode("utf-8")
    return hashlib.sha256(_TOKEN_DOMAIN + normalized).hexdigest()


def verify_access_token(token: str, expected_hash: str) -> bool:
    if not token or not expected_hash:
        return False
    return hmac.compare_digest(hash_access_token(token), expected_hash)


def session_cookie_value(token_hash: str) -> str:
    if not token_hash:
        return ""
    return hmac.new(
        token_hash.encode("ascii", errors="ignore"),
        _SESSION_DOMAIN,
        hashlib.sha256,
    ).hexdigest()


def verify_session_cookie(value: str, token_hash: str) -> bool:
    expected = session_cookie_value(token_hash)
    return bool(value and expected and hmac.compare_digest(value, expected))


def is_loopback_host(host: Optional[str]) -> bool:
    value = str(host or "").strip().split("%", 1)[0]
    if not value:
        return False
    if value.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def client_host(scope: Scope) -> str:
    client = scope.get("client")
    return str(client[0]) if client else ""


def scope_cookie(scope: Scope, name: str = SESSION_COOKIE) -> str:
    raw_cookie = ""
    for key, value in scope.get("headers", []):
        if key.lower() == b"cookie":
            raw_cookie = value.decode("latin-1")
            break
    if not raw_cookie:
        return ""
    parsed = SimpleCookie()
    try:
        parsed.load(raw_cookie)
    except Exception:
        return ""
    morsel = parsed.get(name)
    return morsel.value if morsel else ""


def scope_has_valid_session(scope: Scope, token_hash: Optional[str] = None) -> bool:
    expected_hash = token_hash
    if expected_hash is None:
        expected_hash = load_network_settings()["token_hash"]
    return verify_session_cookie(scope_cookie(scope), expected_hash)


def lan_ipv4_addresses() -> list[str]:
    """Return stable, non-loopback IPv4 candidates for display in settings."""
    candidates: list[str] = []
    primary = ""

    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            candidates.append(str(item[4][0]))
    except OSError:
        pass

    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("192.0.2.1", 80))
            primary = str(probe.getsockname()[0])
        finally:
            probe.close()
    except OSError:
        pass

    result = []
    for value in ([primary] if primary else candidates):
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            continue
        if address.version != 4 or address.is_loopback or address.is_link_local:
            continue
        if value not in result:
            result.append(value)
    return result


def lan_access_urls(port: int = DEFAULT_PORT) -> list[str]:
    return [f"http://{address}:{port}" for address in lan_ipv4_addresses()]


def is_public_remote_path(path: str) -> bool:
    if path in {"/", "/index.html", "/api/network/session", "/api/network/login"}:
        return True
    return path.startswith(("/css/", "/js/", "/vendor/"))


class NetworkAccessMiddleware:
    """Require a LAN session for every non-static HTTP and WebSocket request."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        if not is_lan_access_active() or is_loopback_host(client_host(scope)):
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))
        if scope["type"] == "http" and is_public_remote_path(path):
            await self.app(scope, receive, send)
            return

        token_hash = load_network_settings()["token_hash"]
        if scope_has_valid_session(scope, token_hash):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4401, "reason": "LAN login required"})
            return

        response = JSONResponse(
            {"detail": "LAN login required", "code": "lan_auth_required"},
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )
        await response(scope, receive, send)
