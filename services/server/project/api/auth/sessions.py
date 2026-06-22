from datetime import datetime, timezone

from project import db
from project.api.auth.models import UserSession


def create_session(sid, user_email, expires_at, ip=None, user_agent=None):
    db.session.add(
        UserSession(
            sid=sid,
            user_email=user_email,
            expires_at=expires_at,
            ip=ip,
            user_agent=(user_agent or "")[:256],
        )
    )
    db.session.commit()


def revoke_session(sid):
    s = UserSession.query.filter_by(sid=sid).first()
    if s and s.revoked_at is None:
        s.revoked_at = datetime.now(timezone.utc)
        db.session.commit()


def revoke_all_for_user(user_email):
    now = datetime.now(timezone.utc)
    UserSession.query.filter_by(user_email=user_email, revoked_at=None).update(
        {"revoked_at": now}
    )
    db.session.commit()


def _as_utc(dt) -> datetime:
    """Return *dt* as an aware UTC datetime, adding tzinfo if SQLite stripped it."""
    if dt is None:
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_revoked(sid) -> bool:
    """A missing, revoked, or expired session id is treated as revoked."""
    if not sid:
        return True
    s = UserSession.query.filter_by(sid=sid).first()
    if s is None or s.revoked_at is not None:
        return True
    if s.expires_at is None:
        return False
    return _as_utc(s.expires_at) < datetime.now(timezone.utc)


def purge_expired():
    UserSession.query.filter(
        UserSession.expires_at < datetime.now(timezone.utc)
    ).delete()
    db.session.commit()
