from flask_jwt_extended import get_jwt_identity
from flask import request, make_response, jsonify
from functools import wraps

from project.api.auth.models import get_session_token
from project.logger import get_logger

logger = get_logger(__name__)


def prevent_multiple_logins_per_user():
    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            # check user
            current_user = get_jwt_identity()
            current_user_token = get_session_token(current_user)
            session_token = request.headers.get('Authorization').split(" ")[1]
            if current_user_token != session_token:
                e = PermissionError("Access denied because a new login is done to the account outside the session. Please login again.")
                logger.exception(e)
                logger.debug(f"current_user_token: {current_user_token}, session_token: {session_token}")
                return make_response(jsonify({'message': str(e)}), 401)
            else:
                return fn(*args, **kwargs)
        return decorator
    return wrapper
