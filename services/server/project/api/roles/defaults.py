from project import db
from project.api.roles.models import RoleModel

SYSADMIN_ROLE = "sysadmin"

DEFAULT_ROLES = [
    {
        "name": "sysadmin",
        "description": "Full administrative access. Built-in and protected.",
        "permissions": ["*"],
        "is_system": True,
    },
    {
        "name": "analyst",
        "description": "Runs the full modelling workflow.",
        "permissions": [
            "dataset:read",
            "dataset:write",
            "model_config:read",
            "model_config:write",
            "calibration:read",
            "calibration:write",
            "calibration:execute",
            "forecast:read",
            "forecast:write",
            "forecast:execute",
            "evaluation:read",
            "credit_risk:read",
            "credit_risk:write",
            "credit_risk:execute",
        ],
        "is_system": False,
    },
    {
        "name": "viewer",
        "description": "Read-only access to the modelling workflow.",
        "permissions": [
            "dataset:read",
            "model_config:read",
            "calibration:read",
            "forecast:read",
            "evaluation:read",
            "credit_risk:read",
        ],
        "is_system": False,
    },
]


def ensure_default_roles():
    """Idempotently insert the built-in roles. Safe to call on boot/seed/tests.

    Existing custom-edited roles are left alone; only the protected sysadmin row
    is kept authoritative (always all-perms, always is_system).
    """
    changed = False
    for spec in DEFAULT_ROLES:
        existing = RoleModel.query.filter_by(name=spec["name"]).first()
        if existing is None:
            db.session.add(RoleModel(**spec))
            changed = True
        elif spec["is_system"] and (
            list(existing.permissions or []) != spec["permissions"]
            or not existing.is_system
        ):
            existing.permissions = spec["permissions"]
            existing.is_system = True
            changed = True
    if changed:
        db.session.commit()
