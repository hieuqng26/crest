"""Entrypoint: ``python -m project.mcp_server``.

Transport is chosen by ``MCP_TRANSPORT`` (``stdio`` default, or
``streamable-http`` for a remote networked service). stdio discipline: the MCP
protocol owns stdout — project logging goes to stderr, and ``APP_DB_ECHO`` is
kept off.
"""

import os

from project.logger import get_logger

logger = get_logger(__name__)


def main() -> None:
    # Load an explicit env file BEFORE importing `project` — project.config
    # reads os.getenv at import time. Lets `.mcp.json` point at env/.env.dev
    # (override the docker hostnames with localhost ones alongside it).
    env_file = os.getenv("ENV_FILE")
    if env_file:
        from dotenv import load_dotenv

        load_dotenv(env_file)

    from project.mcp_server import settings
    from project.mcp_server.runtime import get_app
    from project.mcp_server.server import mcp

    # Fail fast on missing/invalid config (CONFIG_NAME, JWT_SECRET_KEY, DB
    # settings) before accepting any client request.
    get_app()

    if settings.transport() == settings.STREAMABLE_HTTP:
        _run_streamable_http(mcp)
    else:
        mcp.run()  # stdio


def _run_streamable_http(mcp) -> None:
    """Serve the streamable-http transport behind bearer-token auth.

    ``load_http_settings`` raises if ``MCP_AUTH_TOKEN`` is unset, so the network
    endpoint can never start unauthenticated. TLS + rate limiting belong at the
    ingress in front of this.
    """
    import uvicorn

    from project.mcp_server import settings
    from project.mcp_server.http_app import build_app

    cfg = settings.load_http_settings()
    app = build_app(mcp, cfg)

    logger.info(
        "Starting CREST MCP server (streamable-http) on %s:%s%s",
        cfg.host,
        cfg.port,
        cfg.path,
    )
    # log_config=None: keep uvicorn from installing its own stdout handlers.
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info", log_config=None)


if __name__ == "__main__":
    main()
