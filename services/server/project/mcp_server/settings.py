"""Transport settings for the MCP server (env-driven).

stdio needs nothing here. The streamable-http transport is a networked service,
so its settings are validated fail-closed: without ``MCP_AUTH_TOKEN`` the server
refuses to start rather than expose an unauthenticated endpoint.
"""

import os
from dataclasses import dataclass

STDIO = "stdio"
STREAMABLE_HTTP = "streamable-http"


def transport() -> str:
    """Selected transport (``MCP_TRANSPORT``); defaults to stdio."""
    return (os.getenv("MCP_TRANSPORT") or STDIO).strip()


def _csv(name: str) -> list[str]:
    return [v.strip() for v in (os.getenv(name) or "").split(",") if v.strip()]


def _flag(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class HttpSettings:
    host: str
    port: int
    path: str
    auth_token: str
    # DNS-rebinding protection (validates the Host/Origin headers). Keep it on
    # in production and list your public hostname(s) in MCP_ALLOWED_HOSTS; the
    # SDK rejects any other Host with 421. Disable it only when a trusted
    # ingress already validates Host (then Host checks happen upstream).
    allowed_hosts: list[str]
    allowed_origins: list[str]
    disable_dns_rebinding_protection: bool


def load_http_settings() -> HttpSettings:
    """Build + validate the streamable-http settings.

    Raises ``RuntimeError`` if ``MCP_AUTH_TOKEN`` is missing/blank — the bearer
    token is the trust boundary for the network endpoint, so an unauthenticated
    start must be impossible (mirrors the ``JWT_SECRET_KEY`` guard in
    ``create_app``).
    """
    token = (os.getenv("MCP_AUTH_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "MCP_AUTH_TOKEN is required for the streamable-http transport — "
            "refusing to start an unauthenticated network MCP endpoint. Set it "
            "to a strong secret shared with your MCP clients."
        )
    origins = _csv("MCP_ALLOWED_ORIGINS") or _csv("MCP_ALLOWED_HOSTS")
    return HttpSettings(
        host=os.getenv("MCP_HOST", "0.0.0.0"),
        port=int(os.getenv("MCP_PORT", "8090")),
        path=os.getenv("MCP_STREAMABLE_PATH", "/mcp"),
        auth_token=token,
        allowed_hosts=_csv("MCP_ALLOWED_HOSTS"),
        allowed_origins=origins,
        disable_dns_rebinding_protection=_flag("MCP_DISABLE_DNS_REBINDING_PROTECTION"),
    )
