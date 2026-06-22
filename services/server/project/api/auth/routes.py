import uuid
from datetime import datetime, timezone

from flask import Blueprint, jsonify, make_response, request
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_jwt,
    get_jwt_identity,
    jwt_required,
    set_access_cookies,
    set_refresh_cookies,
    unset_jwt_cookies,
)

from project import bcrypt, db
from project.api.auditlog.models import log_audit
from project.api.auth import security, sessions
from project.api.roles.registry import permissions_for
from project.api.users.models import User
from project.api.utils import validate_request
from project.logger import get_logger

auth = Blueprint("auth", __name__)
logger = get_logger(__name__)


def _client_ip() -> str:
    return (
        (request.headers.get("X-Forwarded-For", request.remote_addr) or "")
        .split(",")[0]
        .strip()
    )


def _issue_session(user) -> tuple:
    """Create a single fresh session; return (access_token, refresh_token, sid)."""
    sessions.revoke_all_for_user(user.email)  # single active session
    sid = uuid.uuid4().hex
    claims = {"role": user.role, "sid": sid}
    access = create_access_token(identity=user.email, additional_claims=claims)
    refresh = create_refresh_token(identity=user.email, additional_claims=claims)
    exp = datetime.fromtimestamp(decode_token(refresh)["exp"], tz=timezone.utc)
    sessions.create_session(
        sid, user.email, exp, _client_ip(), request.headers.get("User-Agent")
    )
    return access, refresh, sid


@auth.post("/login")
@validate_request(allowed_keys=["email", "password"])
def login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    ip = _client_ip()

    if security.is_locked(email, ip):
        return jsonify(
            {
                "type": "Authentication Error",
                "message": "Account temporarily locked. Try again later.",
            }
        ), 429

    try:
        user = User.authenticate(email, password)
    except Exception:
        user = None

    if not user:
        security.record_failure(email, ip)
        log_audit(
            action="Login",
            user_email=email,
            module="uam",
            submodule="user",
            description="User [$USER] failed to login",
            error_codes="401",
            database_involved="users",
        )
        return jsonify(
            {"type": "Authentication Error", "message": "Invalid username or password"}
        ), 401

    security.clear_failures(email, ip)
    access, refresh, _ = _issue_session(user)
    resp = make_response(
        jsonify(
            {"user": user.to_dict(), "permissions": sorted(permissions_for(user.role))}
        ),
        200,
    )
    set_access_cookies(resp, access)
    set_refresh_cookies(resp, refresh)
    log_audit(
        action="Login",
        user_email=user.email,
        module="uam",
        submodule="user",
        description="User [$USER] logged in",
        error_codes="",
        database_involved="users",
    )
    return resp


@auth.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    sid = get_jwt().get("sid")
    if sessions.is_revoked(sid):
        return jsonify(
            {"type": "Authentication Error", "message": "Session revoked"}
        ), 401
    user = User.query.filter_by(email=identity).first()
    if not user or user.status != "active":
        return jsonify(
            {"type": "Authentication Error", "message": "User inactive"}
        ), 401
    access = create_access_token(
        identity=identity, additional_claims={"role": user.role, "sid": sid}
    )
    resp = make_response(jsonify({"ok": True}), 200)
    set_access_cookies(resp, access)
    return resp


@auth.post("/logout")
@jwt_required()
def logout():
    sid = get_jwt().get("sid")
    sessions.revoke_session(sid)
    email = get_jwt_identity()
    user = User.query.filter_by(email=email).first()
    if user:
        user.last_logout = datetime.now(timezone.utc)
        db.session.commit()
    log_audit(
        action="Logout",
        user_email=email,
        module="uam",
        submodule="user",
        description="User [$USER] logged out",
        error_codes="",
        database_involved="users",
    )
    resp = make_response(jsonify({"logout": True}), 200)
    unset_jwt_cookies(resp)
    return resp


@auth.get("/me")
@jwt_required()
def me():
    user = User.query.filter_by(email=get_jwt_identity()).first()
    if not user:
        return jsonify({"type": "Authentication Error", "message": "Unknown user"}), 401
    return jsonify(
        {"user": user.to_dict(), "permissions": sorted(permissions_for(user.role))}
    ), 200


@auth.post("/change-password")
@jwt_required()
@validate_request(allowed_keys=["current_password", "new_password"])
def change_password():
    data = request.get_json() or {}
    user = User.query.filter_by(email=get_jwt_identity()).first()
    if not user or not bcrypt.check_password_hash(
        user.password, data.get("current_password", "")
    ):
        return jsonify({"message": "Current password is incorrect"}), 400
    try:
        security.validate_password_strength(data.get("new_password", ""))
    except ValueError as e:
        return jsonify({"message": str(e)}), 400
    user.password = bcrypt.generate_password_hash(data["new_password"]).decode("utf-8")
    db.session.commit()
    sessions.revoke_all_for_user(user.email)  # force re-login everywhere
    resp = make_response(jsonify({"ok": True}), 200)
    unset_jwt_cookies(resp)
    return resp
