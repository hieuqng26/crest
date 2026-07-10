"""Transport-agnostic domain exceptions.

Services (and, later, MCP tools) raise these instead of constructing Flask
responses, so business logic never imports ``flask``. The global error boundary
(``project.api.error_handlers``) maps each one to an HTTP status + JSON body.

Body shape is ``{"error": <message>, **payload}``. This matches what the newer
frontend views read (``response.data.error``); ``ConflictError`` additionally
carries a ``dependencies`` key so the "cannot delete — N dependents" dialogs
keep working unchanged.
"""

from typing import Any


class DomainError(Exception):
    """Base for expected, client-facing failures.

    ``status`` is the HTTP code the boundary returns. ``payload`` is merged
    into the JSON body alongside ``error`` (e.g. dependency lists on 409).
    Unlike a bare ``Exception``, the message here is intended to be shown to
    the caller — the boundary never leaks messages from unexpected exceptions.
    """

    status: int = 400
    code: str = "bad_request"

    def __init__(self, message: str, *, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.payload = payload or {}

    def to_body(self) -> dict[str, Any]:
        return {"error": self.message, **self.payload}


class BadRequestError(DomainError):
    status = 400
    code = "bad_request"


class ValidationFailed(DomainError):
    """Semantic validation failure (distinct from a malformed request body,
    which pydantic raises and the boundary maps on its own)."""

    status = 400
    code = "validation_failed"


class UnprocessableEntityError(DomainError):
    """Request is well-formed but cannot be processed given current state —
    e.g. a required dataset has not been uploaded, or a column named in the
    request is absent from the referenced dataset. Maps to 422."""

    status = 422
    code = "unprocessable_entity"


class ForbiddenError(DomainError):
    status = 403
    code = "forbidden"


class NotFoundError(DomainError):
    status = 404
    code = "not_found"


class ConflictError(DomainError):
    """A delete/mutation blocked by existing dependents (FK, no cascade).

    ``dependencies`` is surfaced to the client so it can list what blocks the
    delete — preserving the existing 409 contract.
    """

    status = 409
    code = "conflict"

    def __init__(
        self,
        message: str,
        *,
        dependencies: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ):
        merged = dict(payload or {})
        if dependencies is not None:
            merged["dependencies"] = dependencies
        super().__init__(message, payload=merged)
