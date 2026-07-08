from datetime import datetime, timezone

from flask import current_app

from project import cache, db
from project.api.auth.models import UserSession


def _ok_key(sid) -> str:
    return f"sess_ok:{sid}"


def _cache_ttl() -> int:
    return int(current_app.config.get("SESSION_REVOCATION_CACHE_TTL", 30))


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
    # Invalidate the "known-good" cache so the revocation takes effect immediately.
    cache.delete(_ok_key(sid))


def revoke_all_for_user(user_email):
    now = datetime.now(timezone.utc)
    # Collect the affected sids BEFORE the bulk update so we can purge their
    # cached "valid" verdicts — the bulk .update() doesn't give us the rows.
    sids = [
        s.sid
        for s in UserSession.query.filter_by(
            user_email=user_email, revoked_at=None
        ).all()
    ]
    UserSession.query.filter_by(user_email=user_email, revoked_at=None).update(
        {"revoked_at": now}
    )
    db.session.commit()
    for sid in sids:
        cache.delete(_ok_key(sid))


def delete_all_for_user(user_email):
    """Permanently delete all session records for a user. Call before deleting the user row."""
    sids = [s.sid for s in UserSession.query.filter_by(user_email=user_email).all()]
    UserSession.query.filter_by(user_email=user_email).delete()
    db.session.commit()
    for sid in sids:
        cache.delete(_ok_key(sid))


def _as_utc(dt) -> datetime:
    """Return *dt* as an aware UTC datetime, adding tzinfo if SQLite stripped it."""
    if dt is None:
        return dt
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _is_expired(expires_at) -> bool:
    if expires_at is None:
        return False
    return _as_utc(expires_at) < datetime.now(timezone.utc)


def is_revoked(sid) -> bool:
    """A missing, revoked, or expired session id is treated as revoked.

    This runs on the JWT blocklist path of EVERY authenticated request. To avoid a
    DB round-trip each time, a "known-good" verdict is cached for a short TTL: we
    store only the session's ``expires_at`` (never a frozen revoked/valid boolean),
    and always re-evaluate expiry live against the current time. Revocation and
    deletion paths purge this key synchronously, so in-app revocation is immediate;
    the TTL only bounds out-of-band (raw-DB) changes.
    """
    if not sid:
        return True

    key = _ok_key(sid)
    cached = cache.get(key)
    if cached is not None:
        # cached is the ISO expires_at (or "" when the session has no expiry).
        expires_at = datetime.fromisoformat(cached) if cached else None
        return _is_expired(expires_at)

    s = UserSession.query.filter_by(sid=sid).first()
    if s is None or s.revoked_at is not None:
        return True

    # Cache only the positive ("not revoked") case; expiry is re-checked live.
    expires_at = _as_utc(s.expires_at)
    cache.set(key, expires_at.isoformat() if expires_at else "", timeout=_cache_ttl())
    return _is_expired(expires_at)


def purge_expired():
    UserSession.query.filter(
        UserSession.expires_at < datetime.now(timezone.utc)
    ).delete()
    db.session.commit()
