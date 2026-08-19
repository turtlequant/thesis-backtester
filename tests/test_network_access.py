import json

import pytest
from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.desktop import network_access
from src.desktop.api.routers import network


@pytest.fixture(autouse=True)
def restore_network_state():
    original_path = network_access.get_config_path()
    network_access.clear_active_lan_access()
    yield
    network_access.set_config_path(original_path)
    network_access.clear_active_lan_access()


def _write_config(path, *, enabled=True, token="research-access"):
    path.write_text(
        json.dumps(
            {
                network_access.LAN_ENABLED_KEY: enabled,
                network_access.LAN_TOKEN_HASH_KEY: network_access.hash_access_token(token),
            }
        ),
        encoding="utf-8",
    )


def _test_app():
    app = FastAPI()
    app.add_middleware(network_access.NetworkAccessMiddleware)
    app.include_router(network.router)

    @app.get("/")
    async def index():
        return {"page": "public"}

    @app.get("/api/private")
    async def private_api():
        return {"ok": True}

    @app.websocket("/api/private-ws")
    async def private_websocket(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("ok")
        await websocket.close()

    return app


def test_bind_host_is_opt_in(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(config_path, enabled=False)
    assert network_access.resolve_bind_host(config_path) == "127.0.0.1"

    _write_config(config_path, enabled=True)
    assert network_access.resolve_bind_host(config_path) == "0.0.0.0"


def test_remote_http_login_protects_api_and_static_page_remains_public(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(config_path)
    network_access.set_config_path(config_path)
    network_access.configure_active_lan_access(True)

    with TestClient(_test_app()) as client:
        assert client.get("/").status_code == 200
        session = client.get("/api/network/session")
        assert session.json() == {
            "required": True,
            "authenticated": False,
            "host": "testclient",
        }

        denied = client.get("/api/private")
        assert denied.status_code == 401
        assert denied.json()["code"] == "lan_auth_required"

        invalid = client.post(
            "/api/network/login", json={"access_token": "wrong-token"}
        )
        assert invalid.status_code == 401

        logged_in = client.post(
            "/api/network/login", json={"access_token": "research-access"}
        )
        assert logged_in.status_code == 200
        assert network_access.SESSION_COOKIE in client.cookies
        assert client.get("/api/private").json() == {"ok": True}


def test_remote_websocket_requires_the_same_session(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(config_path)
    network_access.set_config_path(config_path)
    network_access.configure_active_lan_access(True)

    with TestClient(_test_app()) as client:
        with pytest.raises(WebSocketDisconnect) as denied:
            with client.websocket_connect("/api/private-ws"):
                pass
        assert denied.value.code == 4401

        client.post("/api/network/login", json={"access_token": "research-access"})
        with client.websocket_connect("/api/private-ws") as websocket:
            assert websocket.receive_text() == "ok"


def test_loopback_client_never_needs_lan_login(tmp_path):
    config_path = tmp_path / "config.json"
    _write_config(config_path)
    network_access.set_config_path(config_path)
    network_access.configure_active_lan_access(True)

    with TestClient(_test_app(), client=("127.0.0.1", 50000)) as client:
        session = client.get("/api/network/session").json()
        assert session["required"] is False
        assert session["authenticated"] is True
        assert client.get("/api/private").status_code == 200
