"""Entrypoint: ``python -m project.mcp_server`` (stdio transport).

stdio discipline: the MCP protocol owns stdout. Project logging already goes
to stderr (``project.logger`` uses a bare ``StreamHandler``); never print to
stdout here, and keep ``APP_DB_ECHO`` off.
"""

import os


def main() -> None:
    # Load an explicit env file BEFORE importing `project` — project.config
    # reads os.getenv at import time. Lets `.mcp.json` point at env/.env.dev
    # (override the docker hostnames with localhost ones alongside it).
    env_file = os.getenv("ENV_FILE")
    if env_file:
        from dotenv import load_dotenv

        load_dotenv(env_file)

    from project.mcp_server.runtime import get_app
    from project.mcp_server.server import mcp

    # Fail fast on missing/invalid config (CONFIG_NAME, JWT_SECRET_KEY, DB
    # settings) before accepting any client request.
    get_app()
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
