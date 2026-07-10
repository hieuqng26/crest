"""Tests for the global error boundary (project.api.error_handlers).

Verifies each exception type maps to the right status + JSON body, and that an
unexpected exception is logged and returned as a generic 500 with no internal
detail leaked to the client.

Run from services/server/:
    pytest tests/test_error_handlers.py -v
"""

import pytest
from pydantic import BaseModel, ValidationError

from project.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationFailed,
)


@pytest.fixture()
def boundary_client(app):
    """A test client with throwaway routes that raise each exception type.

    PROPAGATE_EXCEPTIONS is disabled so the generic Exception handler runs
    instead of Flask re-raising under TESTING.
    """
    app.config["PROPAGATE_EXCEPTIONS"] = False

    class _Model(BaseModel):
        n: int

    def _raise_not_found():
        raise NotFoundError("thing not found")

    def _raise_conflict():
        raise ConflictError("blocked", dependencies={"calibration_runs": 3})

    def _raise_forbidden():
        raise ForbiddenError("nope")

    def _raise_bad_request():
        raise BadRequestError("bad input")

    def _raise_validation_failed():
        raise ValidationFailed("segment invalid")

    def _raise_pydantic():
        _Model(n="not-an-int")

    def _raise_unexpected():
        raise RuntimeError("db password is hunter2")  # must NOT reach client

    for rule, fn in [
        ("/t/not-found", _raise_not_found),
        ("/t/conflict", _raise_conflict),
        ("/t/forbidden", _raise_forbidden),
        ("/t/bad-request", _raise_bad_request),
        ("/t/validation-failed", _raise_validation_failed),
        ("/t/pydantic", _raise_pydantic),
        ("/t/unexpected", _raise_unexpected),
    ]:
        app.add_url_rule(rule, rule, fn)

    return app.test_client()


def test_not_found_maps_to_404(boundary_client):
    r = boundary_client.get("/t/not-found")
    assert r.status_code == 404
    assert r.get_json() == {"error": "thing not found"}


def test_conflict_carries_dependencies(boundary_client):
    r = boundary_client.get("/t/conflict")
    assert r.status_code == 409
    body = r.get_json()
    assert body["error"] == "blocked"
    assert body["dependencies"] == {"calibration_runs": 3}


def test_forbidden_maps_to_403(boundary_client):
    r = boundary_client.get("/t/forbidden")
    assert r.status_code == 403
    assert r.get_json() == {"error": "nope"}


def test_bad_request_maps_to_400(boundary_client):
    r = boundary_client.get("/t/bad-request")
    assert r.status_code == 400
    assert r.get_json() == {"error": "bad input"}


def test_validation_failed_maps_to_400(boundary_client):
    r = boundary_client.get("/t/validation-failed")
    assert r.status_code == 400
    assert r.get_json() == {"error": "segment invalid"}


def test_pydantic_validation_maps_to_400_with_detail(boundary_client):
    r = boundary_client.get("/t/pydantic")
    assert r.status_code == 400
    body = r.get_json()
    # error is a human summary naming the offending field; detail is the full list
    assert "n" in body["error"]
    assert isinstance(body["detail"], list) and body["detail"]


def test_unexpected_is_generic_500_without_leak(boundary_client):
    r = boundary_client.get("/t/unexpected")
    assert r.status_code == 500
    body = r.get_json()
    assert body == {"error": "Internal server error"}
    # the internal message must never reach the client
    assert "hunter2" not in r.get_data(as_text=True)


def test_http_exception_keeps_message_shape(client):
    """abort()/JWT-style HTTPExceptions keep the {"message": ...} shape that
    the auth/admin frontend views read. An unauthenticated protected route
    returns 401 via the JWT unauthorized loader."""
    r = client.get("/api/user/all")
    assert r.status_code == 401
    assert "message" in r.get_json()


def test_pydantic_validation_error_is_importable():
    # sanity: the boundary imports pydantic ValidationError from the same place
    with pytest.raises(ValidationError):

        class _M(BaseModel):
            x: int

        _M(x="nope")
