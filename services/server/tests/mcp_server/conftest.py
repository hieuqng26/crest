import pytest


@pytest.fixture()
def mcp_app(app):
    """Point the MCP runtime at the test app.

    ``tool_boundary`` pushes ``runtime.get_app()``'s context per call; in tests
    that must be the fixture app (whose in-memory sqlite has the tables), not a
    freshly-created one.
    """
    from project.mcp_server import runtime

    old = runtime._app
    runtime._app = app
    yield app
    runtime._app = old
