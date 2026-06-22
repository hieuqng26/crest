from functools import wraps


from project.logger import get_logger

logger = get_logger(__name__)


def prevent_multiple_logins_per_user():
    """Legacy decorator — superseded by UserSession blocklist in T7. No-op for now."""

    def wrapper(fn):
        @wraps(fn)
        def decorator(*args, **kwargs):
            return fn(*args, **kwargs)

        return decorator

    return wrapper
