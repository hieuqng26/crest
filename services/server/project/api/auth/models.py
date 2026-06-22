from datetime import datetime, timezone

from project import db


class UserSession(db.Model):
    __tablename__ = "user_sessions"

    sid = db.Column(db.String(36), primary_key=True)
    user_email = db.Column(
        db.String(64), db.ForeignKey("users.email"), nullable=False, index=True
    )
    issued_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(256), nullable=True)

    def to_dict(self):
        return {
            "sid": self.sid,
            "user_email": self.user_email,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "revoked": self.revoked_at is not None,
            "ip": self.ip,
            "user_agent": self.user_agent,
        }
