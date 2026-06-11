from flask import Blueprint, jsonify, make_response, request
from flask_jwt_extended import (create_access_token, create_refresh_token,
                                get_jwt_identity, jwt_required,
                                unset_jwt_cookies)
from datetime import datetime, timezone

from project import db
from project.api.utils import validate_request
from project.api.users.models import User
from project.api.auth.models import add_session, update_session, delete_session
from project.api.auditlog.models import log_audit
from project.logger import get_logger

auth = Blueprint('auth', __name__)
logger = get_logger(__name__)


@auth.route('/login', methods=['POST'])
@validate_request(allowed_keys=['email', 'password'])
def login():
    data = request.get_json()
    username = data['email']
    password = data['password']
    user = None

    try:
        user = User.authenticate(username, password)

        # create jwt tokens
        access_token = create_access_token(identity=user.email)

        # store active sessions
        add_session(user.email, access_token)
        refresh_token = create_refresh_token(identity=user.email)
        response = make_response(jsonify({'user': user.to_dict(), 'jwt': {'accessToken': access_token, 'refreshToken': refresh_token}}), 200)
        response.set_cookie('access_token', access_token, secure=True, httponly=True, samesite="Strict")
        response.set_cookie('refresh_token', refresh_token, secure=True, httponly=True, samesite="Strict")

        log_audit(
            action='Login',
            user_email=user.email,
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description='User [$USER] logged in',
            error_codes='',
            database_involved='users'
        )
        return response

    except Exception as e:
        if user:
            user.last_login_type = "Failed"
        log_audit(
            action='Login',
            user_email=username,
            module='uam',
            submodule='user',
            previous_data='',
            new_data='',
            description=f'User [$USER] failed to login. Error: {str(e)}',
            error_codes='500',
            database_involved='users'
        )
        logger.exception(e)
        return make_response(jsonify({'message': str(e)}), 500)


@auth.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
@validate_request()
def refresh_token():
    identity = get_jwt_identity()
    access_token = create_access_token(identity=identity)
    update_session(identity, access_token)
    response = make_response(jsonify({'accessToken': access_token}), 200)
    response.set_cookie('access_token', access_token, secure=True, httponly=True, samesite="Strict")

    log_audit(
        action='Refresh',
        module='uam',
        submodule='user',
        previous_data='',
        new_data='',
        description='System refreshed token for [$USER]',
        error_codes='',
        database_involved=''
    )
    return response


@auth.route('/logout', methods=['POST'])
@jwt_required()
@validate_request()
def logout():
    # update user logout time
    email = get_jwt_identity()
    delete_session(email)
    user = User.query.filter_by(email=email).first()
    if user:
        user.last_logout = datetime.now(timezone.utc)
        db.session.commit()

    log_audit(
        action='Logout',
        module='uam',
        submodule='user',
        previous_data='',
        new_data='',
        description='User [$USER] logged out',
        error_codes='',
        database_involved='users'
    )
    response = make_response(jsonify({'logout': True}), 200)
    unset_jwt_cookies(response)
    return response
