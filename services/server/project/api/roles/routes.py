import json
import re

from flask import Blueprint, jsonify, make_response, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from werkzeug.exceptions import Conflict

import project.api.roles.roles as roleSettings
from project import db
from project.api.auditlog.models import log_audit
from project.api.auth.decorators import current_role, require_perm
from project.api.auth.permissions import (
    SUPERUSER,
    catalog_payload,
    is_valid_permission,
    normalize_permissions,
)
from project.api.auth.utils import prevent_multiple_logins_per_user
from project.api.roles import registry
from project.api.roles.models import Role, RoleModel
from project.api.roles.roles import roles_required, roles_satisfied_module
from project.api.users.models import User
from project.api.utils import validate_request

role = Blueprint("role", __name__)

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


@role.route("/permissions", methods=["GET"])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_role_permissions():
    """Query all roles"""
    roles, _, _, _ = roleSettings.load_roles_from_db()
    return make_response(jsonify(roles["roles"]), 200)


@role.route("/roles_variable", methods=["GET"])
@validate_request()
def get_roles_variable():
    """Query all roles"""
    return make_response(jsonify(roleSettings.load_roles_from_db()), 200)


@role.route("/all", methods=["GET"])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_all_roles():
    roles_required(
        *roleSettings.getRoles("uam", "read"),
        action="Retrieve",
        module="uam",
        submodule="role",
    )
    """Query all roles"""
    role_permission_list = [
        role_permission.to_dict() for role_permission in Role.query.all()
    ]

    return make_response(jsonify(role_permission_list), 200)


@role.route("/name/<string:name>", methods=["GET"])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def get_role_by_id(id):
    roles_required(
        *roleSettings.getRoles("uam", "read"),
        action="Retrieve",
        module="uam",
        submodule="name",
    )
    """Query role by uid"""
    try:
        role = Role.query.filter_by(id=id).first()
        if not role:
            raise Exception("Role not found")

        # audit log
        log_audit(
            action="Retrieve",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description=f"Role [$USER] retrieved user with id {id}",
            error_codes="",
            database_involved="roles",
        )
        return make_response(jsonify(role.to_dict()), 200)

    except Exception as e:
        log_audit(
            action="Retrieve",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description=f"Role [$USER] failed to retrieve user with id {id}. Error: {str(e)}",
            error_codes="500",
            database_involved="roles",
        )
        return make_response(jsonify({"message": str(e)}), 500)


@role.route("/add_batch", methods=["POST"])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=["roles"])
def add_multi_roles():
    roles_required(
        *roleSettings.getRoles("uam", "write"),
        action="Add",
        module="uam",
        submodule="role",
    )
    """Add multiple roles"""
    try:
        data = request.get_json()
        roles = data.get("roles")
        if not roles:
            raise ValueError("No roles provided")

        for role_data in roles:
            name = role_data.get("name")
            module = role_data.get("module")
            permission_type = role_data.get("permission_type")

            role = Role.query.filter_by(
                name=name, module=module, permission_type=permission_type
            ).first()
            if role:
                continue

            if not name:
                continue

            role = Role(name=name, module=module, permission_type=permission_type)
            db.session.add(role)
            db.session.commit()

        # audit log
        log_audit(
            action="Add",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description="Role [$USER] added multiple roles",
            error_codes="",
            database_involved="roles",
        )
        return make_response(jsonify({"message": "Roles added"}), 201)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action="Add",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description=f"Roles [$USER] failed to add multiple roles. Error: {str(e)}",
            error_codes="500",
            database_involved="roles",
        )
        return make_response(jsonify({"message": str(e)}), 500)


@role.route("/add", methods=["POST"])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=["name", "module", "permission_type"])
def add_user():
    roles_required(
        *roleSettings.getRoles("uam", "write"),
        action="Add",
        module="uam",
        submodule="role",
    )
    """Add role"""
    try:
        data = request.get_json()
        name = data.get("name")
        module = data.get("module")
        permission_type = data.get("permission_type")

        role = Role.query.filter_by(
            name=name, module=module, permission_type=permission_type
        ).first()
        if role:
            raise Conflict("Role already exists")

        if not name:
            raise ValueError("Name is required")

        role = Role(name=name, module=module, permission_type=permission_type)
        db.session.add(role)
        db.session.commit()

        # audit log
        log_audit(
            action="Add",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description=f"Role [$USER] added role {name}",
            error_codes="",
            database_involved="roles",
        )
        return make_response(jsonify(role.to_dict()), 201)

    except Conflict as e:
        db.session.rollback()
        log_audit(
            action="Add",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description=f"Role [$USER] failed to add user {name}. Error: {str(e)}",
            error_codes="409",
            database_involved="roles",
        )
        return make_response(jsonify({"message": str(e)}), 409)

    except ValueError as e:
        db.session.rollback()
        log_audit(
            action="Add",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description=f"Roles [$USER] failed to add user {name}. Error: {str(e)}",
            error_codes="400",
            database_involved="roles",
        )
        return make_response(jsonify({"message": str(e)}), 400)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action="Add",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description=f"Role [$USER] failed to add user {name}. Error: {str(e)}",
            error_codes="500",
            database_involved="roles",
        )
        return make_response(jsonify({"message": str(e)}), 500)


@role.route("/update/<string:id>", methods=["PUT"])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=["id", "name", "module", "permission_type"])
def update_role(id):
    roles_required(
        *roleSettings.getRoles("uam", "write"),
        action="Update",
        module="uam",
        submodule="role",
    )
    """Update role by id"""
    try:
        role = Role.query.filter_by(id=id).first()

        if not role:
            raise Exception("Role not found")

        data = request.get_json()
        name = data.get("name")
        module = data.get("module")
        permission_type = data.get("permission_type")

        previous_data = {}
        new_data = {}

        if name and name != role.name:
            previous_data["name"] = role.name
            new_data["name"] = name
            role.name = name

        if module and module != role.module:
            previous_data["module"] = role.module
            new_data["module"] = module
            role.module = module

        if permission_type and permission_type != role.permission_type:
            previous_data["permission_type"] = role.permission_type
            new_data["permission_type"] = permission_type
            role.permission_type = permission_type

        db.session.commit()

        # audit log
        log_audit(
            action="Update",
            module="uam",
            submodule="role",
            previous_data=json.dumps(previous_data),
            new_data=json.dumps(new_data),
            description=f"Role [$USER] updated role {name}",
            error_codes="",
            database_involved="roles",
        )
        return make_response(jsonify(role.to_dict()), 200)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action="Update",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description=f"Role [$USER] failed to update role {name}. Error: {str(e)}",
            error_codes="500",
            database_involved="roles",
        )
        return make_response(jsonify({"message": str(e)}), 500)


@role.route("/updates", methods=["PUT"])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=["roles"])
def update_roles():
    """Update roles"""
    try:
        roles_satisfied_module("uam", "write", action="Update", submodule="user")
        roles = request.get_json()["roles"]
        for oneOfRoles in roles:
            id = oneOfRoles["id"]

            role = Role.query.filter_by(id=id).first()
            if not role:
                raise Exception("Role not found")

            name = oneOfRoles["name"] if "name" in oneOfRoles.keys() else None
            module = oneOfRoles["module"] if "module" in oneOfRoles.keys() else None
            permission_type = (
                oneOfRoles["permission_type"]
                if "permission_type" in oneOfRoles.keys()
                else None
            )

            previous_data = {}
            new_data = {}

            if name and name != role.name:
                previous_data["name"] = role.name
                new_data["name"] = name
                role.name = name

            if module and module != role.module:
                previous_data["module"] = role.module
                new_data["module"] = module
                role.module = module

            if permission_type and permission_type != role.permission_type:
                previous_data["permission_type"] = role.permission_type
                new_data["permission_type"] = permission_type
                role.permission_type = permission_type

            db.session.commit()

            # audit log
            log_audit(
                action="Update",
                module="uam",
                submodule="role",
                previous_data=json.dumps(previous_data),
                new_data=json.dumps(new_data),
                description=f"User [$USER] updated role {name}",
                error_codes="",
                database_involved="roles",
            )
        return make_response(jsonify({"message": "Roles updated"}), 201)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action="Update",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description=f"User [$USER] failed to update roles. Error: {str(e)}",
            error_codes="500",
            database_involved="roles",
        )
        return make_response(jsonify({"message": str(e)}), 500)


@role.route("/delete/<string:id>", methods=["DELETE"])
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request()
def delete_role(id):
    roles_required(
        *roleSettings.getRoles("uam", "write"),
        action="Delete",
        module="uam",
        submodule="role",
    )
    """Delete role by id"""
    try:
        role = Role.query.filter_by(id=id).first()
        if not role:
            raise Exception("Role not found")
        db.session.delete(role)
        db.session.commit()

        # audit log
        log_audit(
            action="Delete",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description=f"Role [$USER] deleted role with id {id}",
            error_codes="",
            database_involved="roles",
        )
        return make_response(jsonify({"message": "User deleted"}), 200)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action="Delete",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description=f"Role [$USER] failed to delete role with id {id}. Error: {str(e)}",
            error_codes="500",
            database_involved="roles",
        )
        return make_response(jsonify({"message": str(e)}), 500)


@role.route(
    "/delete_batch", methods=["POST"]
)  # use POST instead of DELETE which httpClient does not support body parameter
@jwt_required()
@prevent_multiple_logins_per_user()
@validate_request(allowed_keys=["roleIds"])
def delete_multi_roles():
    roles_required(
        *roleSettings.getRoles("uam", "write"),
        action="Delete",
        module="uam",
        submodule="role",
    )
    """Delete role by id"""
    try:
        data = request.get_json()
        roleIds = data.get("roleIds")
        for id in roleIds:
            role = Role.query.filter_by(id=id).first()
            if not role:
                raise Exception("Role not found")
            db.session.delete(role)
        db.session.commit()

        # audit log
        log_audit(
            action="Delete",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description=f"Role [$USER] deleted {len(roleIds)} roles",
            error_codes="",
            database_involved="roles",
        )
        return make_response(jsonify({"message": "User deleted"}), 200)

    except Exception as e:
        log_audit(
            action="Delete",
            module="uam",
            submodule="role",
            previous_data="",
            new_data="",
            description=f"Role [$USER] failed to delete role with id {id}. Error: {str(e)}",
            error_codes="500",
            database_involved="roles",
        )
        return make_response(jsonify({"message": str(e)}), 500)
