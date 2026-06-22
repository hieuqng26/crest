from project import cache
from project.api.roles.models import RoleModel

_CACHE_KEY = "rbac:role_perm_map"
_TTL = 300  # seconds; also explicitly invalidated on every role write


def _load() -> dict:
    return {r.name: set(r.permissions or []) for r in RoleModel.query.all()}


def permission_map() -> dict:
    cached = cache.get(_CACHE_KEY)
    if cached is None:
        cached = _load()
        cache.set(_CACHE_KEY, cached, timeout=_TTL)
    return cached


def permissions_for(role_name) -> set:
    return permission_map().get(role_name or "", set())


def invalidate():
    cache.delete(_CACHE_KEY)
