"""Bearer-token auth for the streamable-http transport.

A pure-ASGI middleware (added via Starlette ``add_middleware`` so the session
manager lifespan is preserved) that requires ``Authorization: Bearer <token>``
on every request except the liveness probe. Constant-time comparison; the token
is never logged. This is the app-level trust boundary — deploy behind TLS + rate
limiting at the ingress.
"""

import hmac

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import Receive, Scope, Send

# Unauthenticated liveness path for load balancers / orchestrators.
HEALTH_PATH = "/healthz"


class BearerAuthMiddleware:
    def __init__(self, app, token: str):
        self.app = app
        self._token = token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Pass lifespan/websocket scopes straight through (keeps the MCP session
        # manager's startup/shutdown intact).
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope.get("path") == HEALTH_PATH:
            await PlainTextResponse("ok")(scope, receive, send)
            return

        if not self._authorized(scope):
            await JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )(scope, receive, send)
            return

        await self.app(scope, receive, send)

    def _authorized(self, scope: Scope) -> bool:
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                parts = value.decode("latin-1").split(" ", 1)
                if len(parts) == 2 and parts[0].lower() == "bearer":
                    # Constant-time compare so a wrong token can't be timed out.
                    return hmac.compare_digest(parts[1], self._token)
        return False
