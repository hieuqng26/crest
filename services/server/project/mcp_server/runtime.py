"""MCP-side runtime plumbing: app bootstrap, identity, and the error boundary.

Mirrors what ``project/api`` provides for the Flask transport — the boundary
here maps the same ``DomainError`` hierarchy to MCP tool errors the way
``api/error_handlers.py`` maps it to HTTP statuses.
"""

import functools
import os
import threading

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from project.exceptions import DomainError
from project.logger import get_logger

logger = get_logger(__name__)

# Service-account identity recorded as triggered_by/created_by on every run
# the MCP server launches. No RBAC in v1 — access control is "whoever can
# start the process with these credentials".
MCP_IDENTITY = os.getenv("MCP_IDENTITY", "mcp-agent")

_app = None
_app_lock = threading.Lock()


def get_app():
    """The lazily-created singleton Flask app (config/DB wiring only — no HTTP
    server runs). Requires the same env as the API process: ``CONFIG_NAME``
    and ``JWT_SECRET_KEY`` are hard-required by ``create_app()`` even though
    the MCP server never mints JWTs."""
    global _app
    if _app is None:
        with _app_lock:
            if _app is None:
                from project import config as project_config
                from project import create_app

                # stdout carries the MCP JSON-RPC stream — SQLAlchemy's echo
                # handler writes to stdout and would corrupt it, so force it
                # off in this process regardless of what the active config
                # (APP_DB_ECHO / TestingConfig) says. Must happen BEFORE
                # create_app(): Flask-SQLAlchemy 3 creates engines during
                # init_app, and echo installs its stdout handler right there.
                for cls in (
                    project_config.Config,
                    project_config.DevelopmentConfig,
                    project_config.ProductionConfig,
                    project_config.TestingConfig,
                ):
                    cls.SQLALCHEMY_ECHO = False

                _app = create_app()
    return _app


def _domain_tool_error(exc: DomainError) -> ToolError:
    body = exc.to_body()
    detail = {k: v for k, v in body.items() if k != "error"}
    suffix = f" {detail}" if detail else ""
    return ToolError(f"[{exc.code}] {exc.message}{suffix}")


def _validation_tool_error(exc: ValidationError) -> ToolError:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(p) for p in first.get("loc", ()))
    msg = first.get("msg", "Invalid request")
    return ToolError(
        f"[validation_failed] {loc}: {msg}" if loc else f"[validation_failed] {msg}"
    )


def tool_boundary(fn):
    """Per-call app context + DomainError→ToolError mapping for every tool.

    FastMCP executes sync tools on worker threads and Flask app contexts /
    ``db.session`` are thread-local, so each call must push its own context
    and drop the scoped session afterwards — never hoist one global
    ``app_context()`` to process start.

    Unexpected exceptions are logged (stderr) and surfaced as a generic
    message: without this, FastMCP would stringify the raw exception into the
    tool result, leaking internals the HTTP boundary deliberately hides.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        from project import db

        with get_app().app_context():
            try:
                return fn(*args, **kwargs)
            except DomainError as exc:
                raise _domain_tool_error(exc) from exc
            except ValidationError as exc:
                raise _validation_tool_error(exc) from exc
            except ToolError:
                raise
            except Exception:
                logger.exception("Unhandled error in MCP tool %s", fn.__name__)
                raise ToolError("Internal server error")
            finally:
                db.session.remove()

    return wrapper
