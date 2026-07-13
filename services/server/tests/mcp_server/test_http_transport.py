"""Streamable-http transport: bearer-token auth and fail-closed config.

These exercise the ASGI layer directly (no network). The full MCP handshake
over HTTP is verified against the running `mcp` container, not here.
"""

import pytest
from starlette.testclient import TestClient

from project.mcp_server import settings
from project.mcp_server.http_app import build_app

TOKEN = "test-mcp-token-abc123"


def _cfg(token: str = TOKEN) -> settings.HttpSettings:
    # DNS-rebinding protection off so the TestClient's Host is accepted; auth is
    # what these tests assert.
    return settings.HttpSettings(
        host="127.0.0.1",
        port=8090,
        path="/mcp",
        auth_token=token,
        allowed_hosts=[],
        allowed_origins=[],
        disable_dns_rebinding_protection=True,
    )


@pytest.fixture(scope="module")
def http_client():
    # Module-scoped: FastMCP's streamable-http session manager can only be
    # started once per server instance, so all auth checks share one client.
    from project.mcp_server.server import mcp

    app = build_app(mcp, _cfg())
    with TestClient(app) as client:
        yield client


def test_missing_token_is_unauthorized(http_client):
    r = http_client.get("/mcp")
    assert r.status_code == 401
    assert r.headers.get("WWW-Authenticate") == "Bearer"


def test_wrong_token_is_unauthorized(http_client):
    r = http_client.get("/mcp", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_non_bearer_scheme_is_unauthorized(http_client):
    r = http_client.get("/mcp", headers={"Authorization": f"Basic {TOKEN}"})
    assert r.status_code == 401


def test_health_probe_needs_no_auth(http_client):
    r = http_client.get("/healthz")
    assert r.status_code == 200
    assert r.text == "ok"


def test_valid_token_reaches_mcp_app(http_client):
    # A bare GET with the right token passes auth and is handled by the MCP app
    # (which rejects the non-MCP request with its own status) — never 401.
    r = http_client.get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code != 401


def test_load_http_settings_fails_closed_without_token(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN is required"):
        settings.load_http_settings()

    monkeypatch.setenv("MCP_AUTH_TOKEN", "   ")  # blank counts as unset
    with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN is required"):
        settings.load_http_settings()


def test_load_http_settings_reads_env(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "s3cret")
    monkeypatch.setenv("MCP_PORT", "9191")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "a.example.com, b.example.com")
    cfg = settings.load_http_settings()
    assert cfg.auth_token == "s3cret"
    assert cfg.port == 9191
    assert cfg.allowed_hosts == ["a.example.com", "b.example.com"]
    # allowed_origins defaults to allowed_hosts when unset
    assert cfg.allowed_origins == ["a.example.com", "b.example.com"]


def test_transport_defaults_to_stdio(monkeypatch):
    monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    assert settings.transport() == settings.STDIO
    monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
    assert settings.transport() == settings.STREAMABLE_HTTP
