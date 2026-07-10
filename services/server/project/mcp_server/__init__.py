"""CREST MCP server — a sibling transport to ``project/api``.

Exposes the transport-agnostic ``project/services/*`` functions as MCP tools
over stdio. Import ``project.mcp_server.server`` to get the configured
``FastMCP`` instance; run with ``python -m project.mcp_server``.

Kept import-side-effect free: importing this package must not create the Flask
app or touch the DB (tests import tool modules directly).
"""
