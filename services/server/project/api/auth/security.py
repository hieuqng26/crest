import re

from project import cache

MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60
_PWD_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,128}$")


def _key(scope: str, ident: str) -> str:
    return f"login_fail:{scope}:{ident}"


def is_locked(email: str, ip: str) -> bool:
    for scope, ident in (("email", email), ("ip", ip)):
        if (cache.get(_key(scope, ident)) or 0) >= MAX_FAILURES:
            return True
    return False


def record_failure(email: str, ip: str) -> None:
    for scope, ident in (("email", email), ("ip", ip)):
        k = _key(scope, ident)
        cache.set(k, (cache.get(k) or 0) + 1, timeout=LOCK_SECONDS)


def clear_failures(email: str, ip: str) -> None:
    cache.delete(_key("email", email))
    cache.delete(_key("ip", ip))


def validate_password_strength(password: str) -> None:
    if not _PWD_RE.match(password or ""):
        raise ValueError(
            "Password must be 8-128 chars and include at least one letter and one digit"
        )
