import json
import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, make_response, request
from werkzeug.exceptions import Conflict

from project import bcrypt, db
from project.api.auditlog.models import log_audit
from project.api.auth import sessions
from project.api.auth.decorators import require_perm
from project.api.roles.models import RoleModel
from project.api.users.models import User
from project.api.utils import valid_date, valid_uuid, validate_request

user = Blueprint("user", __name__)


def _role_exists(role: str) -> bool:
    return bool(role) and RoleModel.query.filter_by(name=role).first() is not None


@user.route("/all", methods=["GET"])
@require_perm("user:read")
@validate_request()
def get_all_users():
    """Query all users"""
    users_list = [user.to_dict() for user in User.query.all()]
    return make_response(jsonify(users_list), 200)


@user.route("/is_local_system_admin/<string:username>", methods=["GET"])
@require_perm("user:read")
@validate_request()
def get_is_local_system_admin(username):
    LOCAL_SYSTEM_ADMIN_USERNAME = os.getenv("LOCAL_SYSTEM_ADMIN_USERNAME")
    doMatch = username == LOCAL_SYSTEM_ADMIN_USERNAME
    return make_response(jsonify({"doMatch": doMatch}), 200)


@user.route("/id/<string:id>", methods=["GET"])
@require_perm("user:read")
@validate_request()
def get_user_by_id(id):
    """Query user by uid"""
    try:
        id = valid_uuid(id)
        user = User.query.filter_by(id=id).first()
        if not user:
            return make_response(jsonify({"message": "User not found"}), 404)

        # audit log
        log_audit(
            action="Retrieve",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] retrieved user with id {id}",
            error_codes="",
            database_involved="users",
        )
        return make_response(jsonify(user.to_dict()), 200)

    except NameError as e:
        log_audit(
            action="Retrieve",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] failed to retrieve job. Job_id is invalid. Error: {str(e)}",
            error_codes="404",
            database_involved="jobs, jobHistory",
        )
        return make_response(jsonify({"message": str(e)}), 404)

    except Exception as e:
        log_audit(
            action="Retrieve",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] failed to retrieve user with id {id}. Error: {str(e)}",
            error_codes="500",
            database_involved="users",
        )
        return make_response(jsonify({"message": str(e)}), 500)


@user.route("/email/<string:email>", methods=["GET"])
@require_perm("user:read")
@validate_request()
def get_user_by_email(email):
    """Query user by email"""
    try:
        user = User.query.filter_by(email=email).first()
        if not user:
            return make_response(jsonify({"message": "User not found"}), 404)

        # audit log
        log_audit(
            action="Retrieve",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] retrieved user with email {email}",
            error_codes="",
            database_involved="users",
        )
        return make_response(jsonify(user.to_dict()), 200)

    except Exception as e:
        log_audit(
            action="Retrieve",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] failed to retrieve user with email {email}. Error: {str(e)}",
            error_codes="500",
            database_involved="users",
        )
        return make_response(jsonify({"message": str(e)}), 500)


@user.route("/add_batch", methods=["POST"])
@require_perm("user:write")
@validate_request(allowed_keys=["users"])
def add_multi_users():
    """Add multiple users. Every row must carry a valid, existing role."""
    try:
        data = request.get_json()
        users = data.get("users")
        if not users:
            raise ValueError("No users provided")

        errors = []
        for idx, user_data in enumerate(users):
            email = user_data.get("email")
            if not email or not user_data.get("password") or not user_data.get("role"):
                errors.append(f"row {idx + 1}: email, password, and role are required")
            elif not _role_exists(user_data.get("role")):
                errors.append(
                    f"row {idx + 1} ({email}): unknown role '{user_data.get('role')}'"
                )
        if errors:
            return make_response(
                jsonify({"message": "Import rejected", "errors": errors}), 400
            )

        for user_data in users:
            email = user_data.get("email")
            if User.query.filter_by(email=email).first():
                continue
            db.session.add(
                User(
                    email=email,
                    password=user_data.get("password"),
                    role=user_data.get("role"),
                    name=user_data.get("name"),
                    status=user_data.get("status"),
                    registered_on=valid_date(
                        user_data.get("registeredOn", datetime.now(timezone.utc))
                    ),
                )
            )
        db.session.commit()

        log_audit(
            action="Add",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description="User [$USER] added multiple users",
            error_codes="",
            database_involved="users",
        )
        return make_response(jsonify({"message": "Users added"}), 201)
    except Exception as e:
        db.session.rollback()
        log_audit(
            action="Add",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] failed to add multiple users. Error: {str(e)}",
            error_codes="500",
            database_involved="users",
        )
        return make_response(jsonify({"message": str(e)}), 500)


@user.route("/add", methods=["POST"])
@require_perm("user:write")
@validate_request(
    allowed_keys=["email", "password", "role", "name", "status", "registeredOn"]
)
def add_user():
    """Add user"""
    try:
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")
        role = data.get("role")
        name = data.get("name")
        status = data.get("status")
        registered_on = data.get("registeredOn")

        user = User.query.filter_by(email=email).first()
        if user:
            raise Conflict("User already exists")

        if not email or not password or not role:
            raise ValueError("Email, password, and role are required")

        if not _role_exists(role):
            raise ValueError(f"Unknown role '{role}'")

        user_kwargs = dict(email=email, password=password, role=role, name=name)
        if status is not None:
            user_kwargs["status"] = status
        if registered_on is not None:
            user_kwargs["registered_on"] = valid_date(registered_on)
        user = User(**user_kwargs)
        db.session.add(user)
        db.session.commit()

        # audit log
        log_audit(
            action="Add",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] added user {email}",
            error_codes="",
            database_involved="users",
        )
        return make_response(jsonify(user.to_dict()), 201)

    except Conflict as e:
        db.session.rollback()
        log_audit(
            action="Add",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] failed to add user {email}. Error: {str(e)}",
            error_codes="409",
            database_involved="users",
        )
        return make_response(jsonify({"message": str(e)}), 409)

    except ValueError as e:
        db.session.rollback()
        log_audit(
            action="Add",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] failed to add user {email}. Error: {str(e)}",
            error_codes="400",
            database_involved="users",
        )
        return make_response(jsonify({"message": str(e)}), 400)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action="Add",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] failed to add user {email}. Error: {str(e)}",
            error_codes="500",
            database_involved="users",
        )
        return make_response(jsonify({"message": str(e)}), 500)


@user.route("/update/<string:email>", methods=["PUT"])
@require_perm("user:write")
@validate_request(
    allowed_keys=["email", "password", "role", "name", "status", "registeredOn"]
)
def update_user(email):
    """Update user by email"""
    try:
        user = User.query.filter_by(email=email).first()

        if not user:
            raise Exception("User not found")

        data = request.get_json()
        email = data.get("email")
        password = data.get("password")
        role = data.get("role")
        name = data.get("name")
        status = data.get("status")
        registered_on = data.get("registeredOn")

        previous_data = {}
        new_data = {}

        if email and email != user.email:
            previous_data["email"] = user.email
            new_data["email"] = email
            user.email = email

        if password and password != user.password:
            password = bcrypt.generate_password_hash(password).decode("utf-8")
            user.password = password

        if role and role != user.role:
            if not _role_exists(role):
                raise ValueError(f"Unknown role '{role}'")
            previous_data["role"] = user.role
            new_data["role"] = role
            user.role = role

        if name and name != user.name:
            previous_data["name"] = user.name
            new_data["name"] = name
            user.name = name

        if status and status != user.status:
            previous_data["status"] = user.status
            new_data["status"] = status
            user.status = status

        if registered_on:
            registered_on = valid_date(registered_on, dayfirst=False)
            if registered_on != user.registered_on:
                previous_data["registered_on"] = user.registered_on.strftime("%Y-%m-%d")
                new_data["registered_on"] = registered_on.strftime("%Y-%m-%d")
                user.registered_on = registered_on

        db.session.commit()

        if "role" in new_data:
            sessions.revoke_all_for_user(user.email)

        # audit log
        log_audit(
            action="Update",
            module="uam",
            submodule="user",
            previous_data=json.dumps(previous_data),
            new_data=json.dumps(new_data),
            description=f"User [$USER] updated user {email}",
            error_codes="",
            database_involved="users",
        )
        return make_response(jsonify(user.to_dict()), 200)

    except ValueError as e:
        db.session.rollback()
        log_audit(
            action="Update",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] failed to update user {email}. Error: {str(e)}",
            error_codes="400",
            database_involved="users",
        )
        return make_response(jsonify({"message": str(e)}), 400)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action="Update",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] failed to update user {email}. Error: {str(e)}",
            error_codes="500",
            database_involved="users",
        )
        return make_response(jsonify({"message": str(e)}), 500)


@user.route("/updates", methods=["PUT"])
@require_perm("user:write")
@validate_request(allowed_keys=["users"])
def update_users():
    """Update users"""
    try:
        users = request.get_json()["users"]
        for oneOfUsers in users:
            email = oneOfUsers["email"]

            user = User.query.filter_by(email=email).first()
            if not user:
                raise Exception("User not found")

            password = (
                oneOfUsers["password"] if "password" in oneOfUsers.keys() else None
            )
            role = oneOfUsers["role"] if "role" in oneOfUsers.keys() else None
            name = oneOfUsers["name"] if "name" in oneOfUsers.keys() else None
            status = oneOfUsers["status"] if "status" in oneOfUsers.keys() else None
            registered_on = (
                oneOfUsers["registeredOn"]
                if "registeredOn" in oneOfUsers.keys()
                else None
            )

            previous_data = {}
            new_data = {}

            if email and email != user.email:
                previous_data["email"] = user.email
                new_data["email"] = email
                user.email = email

            if password and password != user.password:
                password = bcrypt.generate_password_hash(password).decode("utf-8")
                user.password = password

            if role and role != user.role:
                if not _role_exists(role):
                    raise ValueError(f"Unknown role '{role}'")
                previous_data["role"] = user.role
                new_data["role"] = role
                user.role = role

            if name and name != user.name:
                previous_data["name"] = user.name
                new_data["name"] = name
                user.name = name

            if status and status != user.status:
                previous_data["status"] = user.status
                new_data["status"] = status
                user.status = status

            if registered_on:
                registered_on = valid_date(registered_on, dayfirst=False)
                if registered_on != user.registered_on:
                    previous_data["registered_on"] = user.registered_on.strftime(
                        "%Y-%m-%d"
                    )
                    new_data["registered_on"] = registered_on.strftime("%Y-%m-%d")
                    user.registered_on = registered_on

            db.session.commit()

            if "role" in new_data:
                sessions.revoke_all_for_user(user.email)

            # audit log
            log_audit(
                action="Update",
                module="uam",
                submodule="user",
                previous_data=json.dumps(previous_data),
                new_data=json.dumps(new_data),
                description=f"User [$USER] updated user {email}",
                error_codes="",
                database_involved="users",
            )
        return make_response(jsonify({"message": "Users updated"}), 201)

    except ValueError as e:
        db.session.rollback()
        log_audit(
            action="Update",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] failed to update users. Error: {str(e)}",
            error_codes="400",
            database_involved="users",
        )
        return make_response(jsonify({"message": str(e)}), 400)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action="Update",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] failed to update users. Error: {str(e)}",
            error_codes="500",
            database_involved="users",
        )
        return make_response(jsonify({"message": str(e)}), 500)


@user.route("/delete/<string:email>", methods=["DELETE"])
@require_perm("user:write")
@validate_request()
def delete_user(email):
    """Delete user by email"""
    try:
        user = User.query.filter_by(email=email).first()
        if not user:
            raise Exception("User not found")
        sessions.revoke_all_for_user(user.email)  # blocks any active tokens immediately
        sessions.delete_all_for_user(
            user.email
        )  # removes FK-constrained rows so delete succeeds
        db.session.delete(user)
        db.session.commit()

        # audit log
        log_audit(
            action="Delete",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] deleted user {email}",
            error_codes="",
            database_involved="users",
        )
        return make_response(jsonify({"message": "User deleted"}), 200)

    except Exception as e:
        db.session.rollback()
        log_audit(
            action="Delete",
            module="uam",
            submodule="user",
            previous_data="",
            new_data="",
            description=f"User [$USER] failed to delete user {email}. Error: {str(e)}",
            error_codes="500",
            database_involved="users",
        )
        return make_response(jsonify({"message": str(e)}), 500)
