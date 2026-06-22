from datetime import datetime, timezone

from project import db


class RoleModel(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), unique=True, nullable=False, index=True)
    description = db.Column(db.String(256), nullable=True)
    permissions = db.Column(db.JSON, nullable=False, default=list)
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    created_by = db.Column(db.String(64), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self, user_count=None):
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "permissions": list(self.permissions or []),
            "is_system": self.is_system,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if user_count is not None:
            d["user_count"] = user_count
        return d


# Backward-compat alias so legacy routes.py/roles.py can still import `Role`
# until Task 11 removes them.
Role = RoleModel
