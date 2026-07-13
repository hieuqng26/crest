"""Build the authenticated streamable-http ASGI app.

Shared by the ``__main__`` entrypoint and the tests so the transport is wired
one way only.
"""

from mcp.server.transport_security import TransportSecuritySettings

from project.mcp_server.http_auth import BearerAuthMiddleware
from project.mcp_server.settings import HttpSettings


def build_app(mcp, cfg: HttpSettings):
    """Configure the FastMCP instance for stateless HTTP and return its ASGI
    app wrapped in bearer-token auth."""
    mcp.settings.streamable_http_path = cfg.path
    # DNS-rebinding protection: on by default; operator lists allowed hosts, or
    # disables it when a trusted ingress validates Host upstream.
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=not cfg.disable_dns_rebinding_protection,
        allowed_hosts=cfg.allowed_hosts,
        allowed_origins=cfg.allowed_origins,
    )
    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware, token=cfg.auth_token)
    return app
