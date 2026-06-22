import re

from flask import Blueprint, jsonify, make_response, request
from flask_jwt_extended import get_jwt_identity

from project import db
from project.api.auditlog.models import log_audit
from project.api.auth.decorators import current_role, require_perm
from project.api.auth.permissions import (
    SUPERUSER,
    catalog_payload,
    is_valid_permission,
    normalize_permissions,
)
from project.api.roles import registry
from project.api.roles.models import RoleModel
from project.api.users.models import User
from project.api.utils import validate_request  # noqa: F401

# ---------------------------------------------------------------------------
# New roles CRUD blueprint (Task 8)  — mounted at /api/roles
# ---------------------------------------------------------------------------

roles_bp = Blueprint("roles", __name__)
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def _user_counts() -> dict:
    rows = (
        db.session.query(User.role, db.func.count(User.email)).group_by(User.role).all()
    )
    return {r: count for r, count in rows}


def _reject_bad_permissions(permissions):
    """Return a (message, status) tuple if invalid, else None."""
    if SUPERUSER in (permissions or []):
        return ("Cannot grant the wildcard '*' permission", 400)
    invalid = [p for p in (permissions or []) if not is_valid_permission(p)]
    if invalid:
        return (f"Unknown permissions: {', '.join(invalid)}", 400)
    return None


@roles_bp.get("/catalog")
@require_perm("role:read")
def get_catalog():
    return make_response(jsonify(catalog_payload()), 200)


@roles_bp.get("/")
@require_perm("role:read")
def list_roles():
    counts = _user_counts()
    roles = RoleModel.query.order_by(RoleModel.name).all()
    return make_response(
        jsonify([r.to_dict(user_count=counts.get(r.name, 0)) for r in roles]), 200
    )


@roles_bp.post("/")
@require_perm("role:write")
def create_role():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip().lower()
    description = (data.get("description") or "").strip()
    permissions = data.get("permissions") or []

    if not _NAME_RE.match(name):
        return make_response(
            jsonify(
                {
                    "message": "Role name must be lowercase letters/digits/underscores (2-32 chars)"
                }
            ),
            400,
        )
    if RoleModel.query.filter_by(name=name).first():
        return make_response(jsonify({"message": f"Role '{name}' already exists"}), 409)
    bad = _reject_bad_permissions(permissions)
    if bad:
        return make_response(jsonify({"message": bad[0]}), bad[1])

    new_role = RoleModel(
        name=name,
        description=description,
        permissions=normalize_permissions(permissions),
        is_system=False,
        created_by=get_jwt_identity(),
    )
    db.session.add(new_role)
    db.session.commit()
    registry.invalidate()
    log_audit(
        action="Add",
        module="rbac",
        submodule="role",
        previous_data="",
        new_data=name,
        description=f"User [$USER] created role {name}",
        error_codes="",
        database_involved="roles",
    )
    return make_response(jsonify(new_role.to_dict(user_count=0)), 201)


@roles_bp.put("/<string:name>")
@require_perm("role:write")
def update_role_new(name):
    role_obj = RoleModel.query.filter_by(name=name).first()
    if not role_obj:
        return make_response(jsonify({"message": "Role not found"}), 404)
    if role_obj.is_system:
        return make_response(
            jsonify({"message": "Built-in roles cannot be modified"}), 403
        )

    data = request.get_json() or {}
    if "description" in data:
        role_obj.description = (data.get("description") or "").strip()
    if "permissions" in data:
        permissions = data.get("permissions") or []
        bad = _reject_bad_permissions(permissions)
        if bad:
            return make_response(jsonify({"message": bad[0]}), bad[1])
        new_perms = normalize_permissions(permissions)
        # Guard: don't let an admin strip role-management from the role they currently hold
        if role_obj.name == current_role() and "role:write" not in new_perms:
            return make_response(
                jsonify(
                    {
                        "message": "You cannot remove role-management permission from your own role"
                    }
                ),
                400,
            )
        role_obj.permissions = new_perms

    db.session.commit()
    registry.invalidate()
    log_audit(
        action="Update",
        module="rbac",
        submodule="role",
        previous_data="",
        new_data=name,
        description=f"User [$USER] updated role {name}",
        error_codes="",
        database_involved="roles",
    )
    return make_response(jsonify(role_obj.to_dict()), 200)


@roles_bp.delete("/<string:name>")
@require_perm("role:write")
def delete_role_new(name):
    role_obj = RoleModel.query.filter_by(name=name).first()
    if not role_obj:
        return make_response(jsonify({"message": "Role not found"}), 404)
    if role_obj.is_system:
        return make_response(
            jsonify({"message": "Built-in roles cannot be deleted"}), 403
        )
    in_use = User.query.filter_by(role=name).count()
    if in_use:
        return make_response(
            jsonify(
                {
                    "message": f"Role '{name}' is assigned to {in_use} user(s). Reassign them first.",
                    "user_count": in_use,
                }
            ),
            409,
        )
    db.session.delete(role_obj)
    db.session.commit()
    registry.invalidate()
    log_audit(
        action="Delete",
        module="rbac",
        submodule="role",
        previous_data=name,
        new_data="",
        description=f"User [$USER] deleted role {name}",
        error_codes="",
        database_involved="roles",
    )
    return make_response(jsonify({"deleted": name}), 200)
