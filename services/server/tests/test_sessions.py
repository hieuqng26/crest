from datetime import datetime, timedelta, timezone

from project.api.auth import sessions


def _exp():
    return datetime.now(timezone.utc) + timedelta(hours=12)


def test_create_and_revoke(app, make_user):
    make_user("a@x.io", "analyst")
    sessions.create_session("sid-1", "a@x.io", _exp(), "1.1.1.1", "ua")
    assert sessions.is_revoked("sid-1") is False
    sessions.revoke_session("sid-1")
    assert sessions.is_revoked("sid-1") is True


def test_unknown_sid_is_revoked(app):
    assert sessions.is_revoked("does-not-exist") is True


def test_revoke_all_for_user_enforces_single_session(app, make_user):
    make_user("u@x.io", "analyst")
    sessions.create_session("sid-a", "u@x.io", _exp(), None, None)
    sessions.create_session("sid-b", "u@x.io", _exp(), None, None)
    sessions.revoke_all_for_user("u@x.io")
    assert sessions.is_revoked("sid-a") is True
    assert sessions.is_revoked("sid-b") is True
