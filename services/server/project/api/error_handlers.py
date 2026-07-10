"""Global error boundary.

Registered once in ``create_app``. Turns exceptions into JSON responses so no
route needs a catch-all ``try/except`` and no unexpected exception ever leaks a
stack trace or internal message to the client.

Precedence (Flask picks the most specific registered handler):
- ``DomainError``            -> its ``status`` + ``{"error": msg, **payload}``
- pydantic ``ValidationError`` -> 400 + ``{"error": "Validation failed", "detail": [...]}``
- werkzeug ``HTTPException`` -> its own code + ``{"message": description}`` (this
  preserves the shape the auth/JWT flows and ``abort(403/404)`` already emit)
- ``Exception``             -> logged, then generic ``{"error": "Internal server error"}``, 500
"""

from flask import jsonify
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

from project.exceptions import DomainError
from project.logger import get_logger

logger = get_logger(__name__)


def register_error_handlers(app):
    @app.errorhandler(DomainError)
    def _domain_error(exc: DomainError):
        return jsonify(exc.to_body()), exc.status

    @app.errorhandler(ValidationError)
    def _validation_error(exc: ValidationError):
        # Malformed/invalid request body. errors() is JSON-safe and already
        # omits secret values; it only names fields and failed constraints.
        # `error` is a human summary of the first problem (what the frontend
        # toast shows); `detail` carries the full machine-readable list.
        # include_context=False drops pydantic's ``ctx`` — for custom-validator
        # errors it holds the raw ValueError object, which is not JSON-serialisable
        # and would otherwise make jsonify raise (turning a 400 into a 500).
        errors = exc.errors(include_context=False, include_url=False)
        first = errors[0] if errors else {}
        loc = ".".join(str(part) for part in first.get("loc", ()))
        msg = first.get("msg", "Invalid request")
        summary = f"{loc}: {msg}" if loc else msg
        return jsonify({"error": summary, "detail": errors}), 400

    @app.errorhandler(HTTPException)
    def _http_exception(exc: HTTPException):
        # abort(403/404/...) and the JWT callbacks rely on this {"message": ...}
        # shape — several admin/auth frontend views read response.data.message.
        return jsonify({"message": exc.description}), exc.code

    @app.errorhandler(Exception)
    def _unexpected(exc: Exception):
        # The catch-all. Full detail goes to the server log; the client gets a
        # generic body so we never expose internals (contradicting that was the
        # pre-refactor `f"Unexpected error: {e}"` leak pattern).
        logger.exception("Unhandled exception: %s", exc)
        return jsonify({"error": "Internal server error"}), 500
