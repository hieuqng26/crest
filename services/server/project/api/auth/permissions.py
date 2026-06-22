"""Capability model: a static catalog of pages x actions, plus the resolver.

Roles themselves (name -> permission set) are stored in the database and managed
at runtime (see project/api/roles/). This module only defines which permission
strings are *valid* and how a permission set answers a permission check.
"""

SUPERUSER = "*"

# Page (domain) -> the actions that are meaningful for it.
# read = view/list; write = create/edit/delete; execute = run jobs.
PERMISSION_CATALOG: dict[str, list[str]] = {
    "dataset": ["read", "write"],
    "model_config": ["read", "write"],
    "calibration": ["read", "write", "execute"],
    "forecast": ["read", "write", "execute"],
    "evaluation": ["read"],
    "credit_risk": ["read", "write", "execute"],
    "user": ["read", "write"],
    "role": ["read", "write"],
    "auditlog": ["read"],
}

# Human labels for the role-management matrix UI.
PAGE_LABELS: dict[str, str] = {
    "dataset": "Datasets",
    "model_config": "Model Configurations",
    "calibration": "Calibration",
    "forecast": "Forecast",
    "evaluation": "Evaluation",
    "credit_risk": "Credit Risk",
    "user": "User Management",
    "role": "Role Management",
    "auditlog": "Audit Logs",
}
ACTION_LABELS: dict[str, str] = {"read": "Read", "write": "Write", "execute": "Execute"}

ALL_PERMISSIONS: frozenset[str] = frozenset(
    f"{page}:{action}"
    for page, actions in PERMISSION_CATALOG.items()
    for action in actions
)


def is_valid_permission(permission: str) -> bool:
    return permission in ALL_PERMISSIONS


def normalize_permissions(permissions) -> list[str]:
    """Keep only catalog-valid permission strings, de-duplicated and sorted."""
    return sorted({p for p in (permissions or []) if is_valid_permission(p)})


def has_permission(role_permissions, permission: str) -> bool:
    """A permission set grants `permission` if it is the superuser '*' or contains it."""
    if not role_permissions:
        return False
    if SUPERUSER in role_permissions:
        return True
    return permission in role_permissions


def catalog_payload() -> dict:
    """Serializable catalog for the frontend permission matrix."""
    return {
        "pages": [
            {
                "key": page,
                "label": PAGE_LABELS[page],
                "actions": [{"key": a, "label": ACTION_LABELS[a]} for a in actions],
            }
            for page, actions in PERMISSION_CATALOG.items()
        ]
    }
