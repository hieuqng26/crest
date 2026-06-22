from functools import wraps

from flask import abort
from flask_jwt_extended import get_jwt, jwt_required

from project.api.auth.permissions import has_permission
from project.api.roles.registry import permissions_for

try:
    from project.api.auditlog.models import log_audit as _log_audit
except Exception:  # pragma: no cover
    _log_audit = None


def current_role() -> str | None:
    return get_jwt().get("role")


def current_permissions() -> list[str]:
    return sorted(permissions_for(current_role()))


def require_perm(permission: str):
    def wrapper(fn):
        @wraps(fn)
        @jwt_required()
        def inner(*args, **kwargs):
            role = current_role()
            if not has_permission(permissions_for(role), permission):
                if _log_audit is not None:
                    try:
                        _log_audit(
                            action="AccessDenied",
                            module="auth",
                            submodule="",
                            previous_data="",
                            new_data="",
                            description=f"Denied permission '{permission}'",
                            error_codes="403",
                            database_involved="",
                        )
                    except Exception:  # pragma: no cover
                        pass
                abort(403, description="Access forbidden: insufficient privileges")
            return fn(*args, **kwargs)

        return inner

    return wrapper
