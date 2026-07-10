# MCP stdio corrupted by SQLAlchemy echo (stdout is the protocol)

**Symptom**: an MCP client connected to `python -m project.mcp_server` fails
with `Failed to parse JSONRPC message from server` / pydantic
`json_invalid` errors, and the garbage lines are SQL (`PRAGMA …`,
`BEGIN (implicit)`, engine INFO logs).

**Cause**: a stdio MCP server owns stdout — every byte must be JSON-RPC.
`SQLALCHEMY_ECHO = True` (set by `TestingConfig`, or `APP_DB_ECHO=true` under
`DevelopmentConfig`) makes SQLAlchemy install a logging handler that writes to
**stdout**, interleaving SQL with the protocol stream.

**Trap within the trap**: setting `app.config["SQLALCHEMY_ECHO"] = False`
*after* `create_app()` doesn't work — Flask-SQLAlchemy 3 creates engines during
`db.init_app()` (inside `create_app`), and echo wires its handler at engine
creation.

**Fix** (`project/mcp_server/runtime.py::get_app`): force
`SQLALCHEMY_ECHO = False` on all four config **classes** before calling
`create_app()`. Caught by the stdio end-to-end check (real client ↔ subprocess
server), not by unit tests — tool functions called directly never touch stdout.

**Rule**: anything that runs inside the MCP process must log to stderr.
`project.logger`'s `StreamHandler()` already defaults to stderr; never add a
stdout handler or `print()` in code reachable from a tool.
