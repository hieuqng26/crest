# Auth & RBAC Rebuild — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace CREST's inherited ESG role-matrix and header-token auth with capability-based RBAC where **roles and their permissions are managed at runtime through an admin UI**, backed by revocable, cookie-based JWT sessions.

**Architecture:** A permission is a `domain:action` string drawn from a fixed, code-defined **catalog** (the set of pages × the actions `read | write | execute`). A **role** is a named, database-stored bundle of catalog permissions, created and edited at runtime via a role-management page. A user's role name rides in a JWT claim; on each request a single `@require_perm` decorator resolves that role's *current* permission set from a cached **role registry** (so permission edits take effect without re-login) and checks membership. One built-in `sysadmin` role (`["*"]`, `is_system=True`) is immutable and undeletable — the guaranteed recovery path. Auth uses access + refresh JWTs delivered as `HttpOnly; Secure; SameSite=Strict` cookies, with a `user_sessions` table for server-side revocation, single-active-session enforcement, and admin force-logout. The frontend stops storing tokens in JS entirely and drives UI from a `/auth/me` permission list.

**Tech Stack:** Flask, flask-jwt-extended (cookie mode + CSRF double-submit), Flask-SQLAlchemy, Flask-Migrate/Alembic, flask-bcrypt, flask-caching (Redis — login lockout + role registry cache); Vue 3 + Vuex 4 + Vue Router 4 + PrimeVue 3; pytest/pytest-flask, Vitest.

## Relationship to `PRODUCTION_READINESS.md`

**Do this plan first.** It fully resolves roadmap item **S2** (RBAC not enforced) and the token-in-`localStorage` half of **S4**. It also touches the `CORS_ORIGIN` crash (**S5**) because cookie auth depends on correct credentialed CORS — that small guard is folded into Task 3. The final task updates the roadmap to mark these as handled and to point at this plan.

## Global Constraints

- **Roles are runtime data, not code.** They live in the `roles` table and are managed through `/api/roles` + a role-management page. No role enum.
- **Built-in `sysadmin` is protected:** `permissions = ["*"]`, `is_system = True`. It can never be edited or deleted. It is the lockout-recovery guarantee.
- **Permission catalog (the only valid permission strings):** pages `dataset, model_config, calibration, forecast, evaluation, credit_risk, user, role, auditlog`; actions `read | write | execute`. `write` covers create/edit/**delete**; `execute` = running jobs. Not every page has every action (see Task 1 catalog).
- **No wildcards in custom roles.** Only the built-in `sysadmin` may hold `*`. The CRUD API rejects `*` in any create/update payload.
- **Role management is a delegable capability:** gated on `role:write` (edit) / `role:read` (view). By default only `sysadmin` has it; a sysadmin may grant it to a custom role.
- **Permission resolution:** the JWT carries the role **name**; permissions are resolved per-request from the cached role registry (invalidated on every role write). Changing a user's *assigned role* revokes their sessions (forces the new role-name claim).
- **Token transport:** `HttpOnly; Secure; SameSite=Strict` cookies only. **No JWT in `localStorage`/Vuex.**
- **Token lifetimes:** access **15 minutes**, refresh **12 hours**.
- **Single active session per user:** a new login revokes all prior sessions for that user.
- **CSRF:** flask-jwt-extended double-submit (`X-CSRF-TOKEN`). Remove the unused flask-wtf `CSRFProtect`.
- **PrimeVue stays on v3.** Do not introduce v4 APIs.
- **Python:** after every Python edit run, from `services/server/`: `ruff check . --exclude migrations --fix && ruff format . --exclude migrations`.
- **Git:** small, frequent commits. **Never** add `Co-Authored-By` trailers.
- **Tests** run against the SQLite `TestingConfig` via `db.create_all()` (migrations are for the real MSSQL only).

---

## File Structure

**Backend — `project/api/auth/` (auth package already exists):**
- `permissions.py` — catalog (`PERMISSION_CATALOG`, `PAGE_LABELS`, `ACTION_LABELS`), `ALL_PERMISSIONS`, `is_valid_permission()`, `normalize_permissions()`, `has_permission()`, `catalog_payload()`, `SUPERUSER`. **No role enum.**
- `decorators.py` — `require_perm()`, `current_role()`, `current_permissions()` (resolves via the role registry).
- `models.py` — **replace** `ActiveSession` with `UserSession` (`sid` PK).
- `sessions.py` — session service: `create_session`, `revoke_session`, `revoke_all_for_user`, `is_revoked`, `purge_expired`.
- `jwt_callbacks.py` — `register_jwt_callbacks(jwt)`: blocklist loader + error handlers.
- `routes.py` — **rewrite**: `login`, `refresh`, `logout`, `me`, `change_password`.
- `security.py` — login lockout helpers (Redis via `cache`) + `validate_password_strength`.
- **delete** `utils.py`'s `prevent_multiple_logins_per_user` (superseded by the blocklist).

**Backend — NEW `project/api/roles/` (clean re-implementation; legacy package is removed first):**
- `models.py` — `RoleModel` (`roles` table: `name`, `description`, `permissions` JSON, `is_system`, audit cols).
- `defaults.py` — `DEFAULT_ROLES`, `SYSADMIN_ROLE`, `ensure_default_roles()` (idempotent seed).
- `registry.py` — cached `name → set(permissions)` map: `permission_map()`, `permissions_for()`, `invalidate()`.
- `routes.py` — `roles_bp`: `GET /catalog`, `GET /`, `POST /`, `PUT /<name>`, `DELETE /<name>`.

**Backend — removed:**
- Legacy `project/api/roles/` contents (`roles.py`, old `routes.py`, old `models.py`) — replaced by the package above.
- `ActiveSession` model + `active_session` table; **legacy** `roles` table schema (recreated with the new shape).

**Backend — edited:** `project/__init__.py` (JWT cookie config, register callbacks, register new `roles_bp`, drop flask-wtf CSRF), `project/config.py` (JWT cookie settings, lifetimes, `CACHE_TYPE` for testing), every `api/*/routes.py` (add `@require_perm`), `api/users/routes.py` (gate + DB role validation + CSV role column + revoke-on-role-change), `manage.py` (`seed_db`).

**Backend — migrations:** one Alembic revision: drop legacy `roles` + `active_session`; create new `roles` (+ seed 3 roles) and `user_sessions`; normalize `users.role`.

**Backend — tests (`services/server/tests/`):** `conftest.py` (harness), `test_permissions.py`, `test_roles.py` (model+registry), `test_sessions.py`, `test_auth_routes.py`, `test_roles_api.py` (CRUD), `test_rbac_enforcement.py` (endpoint matrix), `test_users_rbac.py`.

**Frontend — `services/client/src/`:**
- `api/httpClient.js` — cookie mode + CSRF header + cookie-based refresh; remove Bearer/localStorage.
- `api/authAPI.js` — `login/refresh/logout/me/changePassword`.
- `api/roleAPI.js` — **rebuilt** for the new roles domain (`list/catalog/create/update/remove`).
- `store/index.js` + `store/actions/authActions.js` — `currentUser` + `permissions`, `/me` bootstrap; **delete** `store/actions/roleActions.js` and role/`ROLES_PER_MODULE` state.
- `utils/permissions.js` — `can(permissions, permission)` (membership + `*`); `directives/can.js` — `v-can`.
- `layout/AppMenu.vue` — filter by `can()`; `router/index.js` — `requiresPerm` guard + role-management route.
- `views/admin/RoleManagement.vue` — **new** role list + permission-matrix editor.
- `views/users/UAM.vue` — rebuild: dynamic role dropdown from `roleAPI`, working manual "New User" button, CSV `role` column.
- Vitest: `vitest.config.js`, `src/utils/__tests__/permissions.spec.js`, `src/api/__tests__/httpClient.spec.js`.

**Docs (final task):** `CLAUDE.md`, `.claude/docs/architecture.md`, `.claude/docs/state_management.md`, `.claude/docs/database_models.md`, `PRODUCTION_READINESS.md`.

---

## Endpoint → permission matrix (reference for Task 10)

Default rule per blueprint: **GET = `domain:read`**, **mutating config/data verbs (POST/PUT/DELETE) = `domain:write`**, **run/compute verbs = `domain:execute`**. `delete` folds into `write`.

| Blueprint (prefix) | Domain | Read → perm | Write (create/edit/delete) → perm | Execute (run) → perm |
|---|---|---|---|---|
| `datasets` (`/api/datasets`) | `dataset` | `dataset:read` | upload/query/PUT/DELETE → `dataset:write` | — |
| `model_configs` (`/api/model-configs`) | `model_config` | `model_config:read` | POST/PUT/DELETE → `model_config:write` | — |
| `calibrations` (`/api/calibrations`) | `calibration` | `calibration:read` | edit/DELETE → `calibration:write` | create/rerun → `calibration:execute` |
| `forecasts` (`/api/forecasts`) | `forecast` | `forecast:read` | DELETE → `forecast:write` | POST/rerun → `forecast:execute` |
| `forecast_runs` (`/api/forecast-runs`) | `forecast` | `forecast:read` | DELETE → `forecast:write` | create/rerun/cancel → `forecast:execute` |
| `evaluations` (`/api/evaluations`) | `evaluation` | `evaluation:read` | (read-only module) | — |
| `credit_risk` (`/api/credit-risk`) | `credit_risk` | `credit_risk:read`; `/kmv` `/ecl` compute → `credit_risk:read` | DELETE → `credit_risk:write` | `/runs` `/rerun` `/cancel` `/active` → `credit_risk:execute` |
| `user` (`/api/user`) | `user` | GET → `user:read` | POST/PUT/DELETE → `user:write` | — |
| `roles` (`/api/roles`) | `role` | GET `/` `/catalog` → `role:read` | POST/PUT/DELETE → `role:write` | — |
| `auditlog` (`/api/log`) | `auditlog` | `auditlog:read` | — | — |

Built-in seed roles: **`viewer`** = read on every business page (`dataset/model_config/calibration/forecast/evaluation/credit_risk:read`). **`analyst`** = viewer + `dataset:write`, `model_config:write`, `calibration:write`, `calibration:execute`, `forecast:write`, `forecast:execute`, `credit_risk:write`, `credit_risk:execute`. **`sysadmin`** = `["*"]`.

---

## Task 1: Permission catalog & resolver (pure, no DB)

**Files:**
- Create: `services/server/project/api/auth/permissions.py`
- Test: `services/server/tests/test_permissions.py`

**Interfaces:**
- Produces: `SUPERUSER = "*"`; `PERMISSION_CATALOG: dict[str, list[str]]`; `PAGE_LABELS`, `ACTION_LABELS: dict[str,str]`; `ALL_PERMISSIONS: frozenset[str]`; `is_valid_permission(p) -> bool`; `normalize_permissions(perms) -> list[str]`; `has_permission(role_permissions, permission) -> bool`; `catalog_payload() -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# services/server/tests/test_permissions.py
import pytest

from project.api.auth.permissions import (
    ALL_PERMISSIONS,
    catalog_payload,
    has_permission,
    is_valid_permission,
    normalize_permissions,
)


@pytest.mark.parametrize("perm,valid", [
    ("dataset:read", True),
    ("credit_risk:execute", True),
    ("user:write", True),
    ("role:read", True),
    ("evaluation:write", False),   # evaluation is read-only
    ("auditlog:write", False),     # auditlog is read-only
    ("dataset:manage", False),     # 'manage' is not an action
    ("nope:read", False),          # unknown page
])
def test_is_valid_permission(perm, valid):
    assert is_valid_permission(perm) is valid


@pytest.mark.parametrize("perms,perm,expected", [
    ({"dataset:read"}, "dataset:read", True),
    ({"dataset:read"}, "dataset:write", False),
    ({"*"}, "anything:at:all", True),       # superuser
    (set(), "dataset:read", False),
    (["dataset:read", "credit_risk:execute"], "credit_risk:execute", True),
])
def test_has_permission(perms, perm, expected):
    assert has_permission(perms, perm) is expected


def test_normalize_drops_invalid_and_sorts():
    assert normalize_permissions(["dataset:write", "bad:perm", "dataset:read", "dataset:read"]) == [
        "dataset:read",
        "dataset:write",
    ]


def test_catalog_payload_shape():
    payload = catalog_payload()
    pages = {p["key"] for p in payload["pages"]}
    assert {"dataset", "credit_risk", "user", "role", "auditlog"} <= pages
    evaluation = next(p for p in payload["pages"] if p["key"] == "evaluation")
    assert [a["key"] for a in evaluation["actions"]] == ["read"]
    assert "credit_risk:execute" in ALL_PERMISSIONS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/server && python3.11 -m pytest tests/test_permissions.py -v`
Expected: FAIL — `ModuleNotFoundError: project.api.auth.permissions`.

- [ ] **Step 3: Write minimal implementation**

```python
# services/server/project/api/auth/permissions.py
"""Capability model: a static catalog of pages x actions, plus the resolver.

Roles themselves (name -> permission set) are stored in the database and managed
at runtime (see project/api/roles/). This module only defines which permission
strings are *valid* and how a permission set answers a permission check.
"""

SUPERUSER = "*"

# Page (domain) -> the actions that are meaningful for it.
# read = view/list; write = create/edit/delete; execute = run jobs.
PERMISSION_CATALOG: dict[str, list[str]] = {
    "dataset": ["read", "write"],
    "model_config": ["read", "write"],
    "calibration": ["read", "write", "execute"],
    "forecast": ["read", "write", "execute"],
    "evaluation": ["read"],
    "credit_risk": ["read", "write", "execute"],
    "user": ["read", "write"],
    "role": ["read", "write"],
    "auditlog": ["read"],
}

# Human labels for the role-management matrix UI.
PAGE_LABELS: dict[str, str] = {
    "dataset": "Datasets",
    "model_config": "Model Configurations",
    "calibration": "Calibration",
    "forecast": "Forecast",
    "evaluation": "Evaluation",
    "credit_risk": "Credit Risk",
    "user": "User Management",
    "role": "Role Management",
    "auditlog": "Audit Logs",
}
ACTION_LABELS: dict[str, str] = {"read": "Read", "write": "Write", "execute": "Execute"}

ALL_PERMISSIONS: frozenset[str] = frozenset(
    f"{page}:{action}"
    for page, actions in PERMISSION_CATALOG.items()
    for action in actions
)


def is_valid_permission(permission: str) -> bool:
    return permission in ALL_PERMISSIONS


def normalize_permissions(permissions) -> list[str]:
    """Keep only catalog-valid permission strings, de-duplicated and sorted."""
    return sorted({p for p in (permissions or []) if is_valid_permission(p)})


def has_permission(role_permissions, permission: str) -> bool:
    """A permission set grants `permission` if it is the superuser '*' or contains it."""
    if not role_permissions:
        return False
    if SUPERUSER in role_permissions:
        return True
    return permission in role_permissions


def catalog_payload() -> dict:
    """Serializable catalog for the frontend permission matrix."""
    return {
        "pages": [
            {
                "key": page,
                "label": PAGE_LABELS[page],
                "actions": [{"key": a, "label": ACTION_LABELS[a]} for a in actions],
            }
            for page, actions in PERMISSION_CATALOG.items()
        ]
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/server && python3.11 -m pytest tests/test_permissions.py -v`
Expected: PASS (all parametrized cases).

- [ ] **Step 5: Lint & commit**

```bash
cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations
git add services/server/project/api/auth/permissions.py services/server/tests/test_permissions.py
git commit -m "feat(auth): add permission catalog and resolver"
```

---

## Task 2: Test harness (conftest with app, seeded roles, role-scoped clients)

**Files:**
- Create: `services/server/tests/conftest.py`

**Interfaces:**
- Produces pytest fixtures: `app` (seeds default roles, clears cache), `client`, `make_user(email, role, password="Passw0rd!")`, `login(client, email, password)`. Consumed by Tasks 5–11.

> If a `conftest.py` already exists, merge these fixtures into it; keep any existing fixtures used by `test_credit_risk.py`.

- [ ] **Step 1: Write the harness**

```python
# services/server/tests/conftest.py
import os

import pytest

os.environ["CONFIG_NAME"] = "testing"
os.environ.setdefault("CORS_ORIGIN", "http://localhost:5173")


@pytest.fixture()
def app():
    from project import cache, create_app, db
    from project.api.roles.defaults import ensure_default_roles

    app = create_app()
    app.config.update(TESTING=True, JWT_COOKIE_CSRF_PROTECT=False, JWT_COOKIE_SECURE=False)
    with app.app_context():
        db.create_all()
        ensure_default_roles()
        cache.clear()  # role registry + login-lockout keys must not leak between tests
        yield app
        db.session.remove()
        db.drop_all()
        cache.clear()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def make_user(app):
    from project import db
    from project.api.users.models import User

    def _make(email, role, password="Passw0rd!"):
        u = User(email=email, password=password, role=role, name=email)
        u.status = "active"
        db.session.add(u)
        db.session.commit()
        return u

    return _make


@pytest.fixture()
def login(client):
    def _login(email, password="Passw0rd!"):
        return client.post("/api/auth/login", json={"email": email, "password": password})

    return _login
```

- [ ] **Step 2: Verify collection works (no tests yet here)**

Run: `cd services/server && python3.11 -m pytest tests/conftest.py -v`
Expected: PASS (0 tests collected, no import errors). Imports of `roles.defaults` etc. land in Task 5; until then this fixture is exercised only by later tasks — proceed.

- [ ] **Step 3: Commit**

```bash
git add services/server/tests/conftest.py
git commit -m "test(auth): add pytest harness with seeded roles"
```

---

## Task 3: JWT cookie configuration & CORS guard

**Files:**
- Modify: `services/server/project/config.py` (JWT cookie settings + lifetimes; testing cache backend)
- Modify: `services/server/project/__init__.py` (apply cookie config; remove flask-wtf `CSRFProtect`; guard `CORS_ORIGIN`)
- Test: `services/server/tests/test_auth_routes.py` (config assertion only here)

**Interfaces:**
- Produces: app configured with `JWT_TOKEN_LOCATION=["cookies"]`, `JWT_COOKIE_CSRF_PROTECT=True`, access=15m, refresh=12h, `CACHE_TYPE="SimpleCache"` under testing. Consumed by Tasks 5–11.

- [ ] **Step 1: Write the failing test**

```python
# services/server/tests/test_auth_routes.py
def test_jwt_is_cookie_mode(app):
    assert app.config["JWT_TOKEN_LOCATION"] == ["cookies"]
    assert app.config["JWT_COOKIE_SAMESITE"] == "Strict"
    assert app.config["JWT_ACCESS_TOKEN_EXPIRES"].total_seconds() == 15 * 60
    assert app.config["JWT_REFRESH_TOKEN_EXPIRES"].total_seconds() == 12 * 60 * 60
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/server && python3.11 -m pytest tests/test_auth_routes.py::test_jwt_is_cookie_mode -v`
Expected: FAIL — token location is still `["headers"]`.

- [ ] **Step 3: Add cookie settings to `config.py` base `Config`**

In `class Config`, replace the JWT block with (ensure `from datetime import timedelta` and `import os` at top):

```python
    # JWT — cookie transport, revocable sessions
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")  # required; no baked-in default
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MIN", 15)))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(hours=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES_H", 12)))
    JWT_TOKEN_LOCATION = ["cookies"]
    JWT_COOKIE_SAMESITE = "Strict"
    JWT_COOKIE_SECURE = os.getenv("JWT_COOKIE_SECURE", "true").lower() == "true"
    JWT_COOKIE_CSRF_PROTECT = True
    JWT_ACCESS_COOKIE_PATH = "/api"
    JWT_REFRESH_COOKIE_PATH = "/api/auth/refresh"
    JWT_SESSION_COOKIE = False  # persist across browser restarts (until refresh expiry)
```

In `TestingConfig` add `JWT_SECRET_KEY = "test-secret"`, `JWT_COOKIE_CSRF_PROTECT = False`, `JWT_COOKIE_SECURE = False`, and `CACHE_TYPE = "SimpleCache"` (the role registry + login lockout both use `cache`). In `DevelopmentConfig` add `JWT_COOKIE_SECURE = os.getenv("JWT_COOKIE_SECURE", "false").lower() == "true"` (dev is http).

- [ ] **Step 4: Update `__init__.py`**

Remove the flask-wtf CSRF block (`CSRFProtect`, `WTF_CSRF_*`) and apply JWT config from the active config object instead of hard-coding `Config.*`:

```python
    # JWT (cookie mode) — values come from the active config object
    jwt = JWTManager(app)

    from project.api.auth.jwt_callbacks import register_jwt_callbacks
    register_jwt_callbacks(jwt)
```

Delete the lines that set `app.config["JWT_*"] = Config.*`. In `after_request`, harden the CORS origin read:

```python
        allowed_origins_env = os.getenv("CORS_ORIGIN", "")
        allowed_origins = [s.strip() for s in allowed_origins_env.split(",") if s.strip()]
```

> To keep Task 3 independently runnable: create `services/server/project/api/auth/jwt_callbacks.py` now with a stub `def register_jwt_callbacks(jwt): pass`. Task 4 replaces the body. (Leave the legacy role blueprint registration for now — Task 11 removes it.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/server && python3.11 -m pytest tests/test_auth_routes.py::test_jwt_is_cookie_mode -v`
Expected: PASS.

- [ ] **Step 6: Lint & commit**

```bash
cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations
git add services/server/project/config.py services/server/project/__init__.py services/server/project/api/auth/jwt_callbacks.py services/server/tests/test_auth_routes.py
git commit -m "feat(auth): switch JWT to cookie transport with 15m/12h lifetimes"
```

---

## Task 4: Session model, service, and JWT blocklist callbacks

**Files:**
- Modify: `services/server/project/api/auth/models.py` (replace `ActiveSession` with `UserSession`)
- Create: `services/server/project/api/auth/sessions.py`
- Modify: `services/server/project/api/auth/jwt_callbacks.py` (real body)
- Test: `services/server/tests/test_sessions.py`

**Interfaces:**
- Produces: `UserSession` model (`sid` PK str(36), `user_email` FK indexed, `issued_at`, `expires_at`, `revoked_at`, `ip`, `user_agent`); `sessions.create_session(sid, user_email, expires_at, ip, user_agent)`, `sessions.revoke_session(sid)`, `sessions.revoke_all_for_user(user_email)`, `sessions.is_revoked(sid) -> bool`, `sessions.purge_expired()`; `register_jwt_callbacks(jwt)`.

- [ ] **Step 1: Write the failing test**

```python
# services/server/tests/test_sessions.py
from datetime import datetime, timedelta, timezone

from project.api.auth import sessions


def _exp():
    return datetime.now(timezone.utc) + timedelta(hours=12)

def test_create_and_revoke(app):
    sessions.create_session("sid-1", "a@x.io", _exp(), "1.1.1.1", "ua")
    assert sessions.is_revoked("sid-1") is False
    sessions.revoke_session("sid-1")
    assert sessions.is_revoked("sid-1") is True

def test_unknown_sid_is_revoked(app):
    assert sessions.is_revoked("does-not-exist") is True

def test_revoke_all_for_user_enforces_single_session(app):
    sessions.create_session("sid-a", "u@x.io", _exp(), None, None)
    sessions.create_session("sid-b", "u@x.io", _exp(), None, None)
    sessions.revoke_all_for_user("u@x.io")
    assert sessions.is_revoked("sid-a") is True
    assert sessions.is_revoked("sid-b") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/server && python3.11 -m pytest tests/test_sessions.py -v`
Expected: FAIL — `sessions` module / `UserSession` missing.

- [ ] **Step 3: Replace `auth/models.py`**

```python
# services/server/project/api/auth/models.py
from datetime import datetime, timezone

from project import db


class UserSession(db.Model):
    __tablename__ = "user_sessions"

    sid = db.Column(db.String(36), primary_key=True)
    user_email = db.Column(
        db.String(64), db.ForeignKey("users.email"), nullable=False, index=True
    )
    issued_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(256), nullable=True)

    def to_dict(self):
        return {
            "sid": self.sid,
            "user_email": self.user_email,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "revoked": self.revoked_at is not None,
            "ip": self.ip,
            "user_agent": self.user_agent,
        }
```

- [ ] **Step 4: Create `auth/sessions.py`**

```python
# services/server/project/api/auth/sessions.py
from datetime import datetime, timezone

from project import db
from project.api.auth.models import UserSession


def create_session(sid, user_email, expires_at, ip=None, user_agent=None):
    db.session.add(
        UserSession(
            sid=sid,
            user_email=user_email,
            expires_at=expires_at,
            ip=ip,
            user_agent=(user_agent or "")[:256],
        )
    )
    db.session.commit()


def revoke_session(sid):
    s = UserSession.query.filter_by(sid=sid).first()
    if s and s.revoked_at is None:
        s.revoked_at = datetime.now(timezone.utc)
        db.session.commit()


def revoke_all_for_user(user_email):
    now = datetime.now(timezone.utc)
    UserSession.query.filter_by(user_email=user_email, revoked_at=None).update(
        {"revoked_at": now}
    )
    db.session.commit()


def is_revoked(sid) -> bool:
    """A missing, revoked, or expired session id is treated as revoked."""
    if not sid:
        return True
    s = UserSession.query.filter_by(sid=sid).first()
    if s is None or s.revoked_at is not None:
        return True
    return s.expires_at is not None and s.expires_at < datetime.now(timezone.utc)


def purge_expired():
    UserSession.query.filter(
        UserSession.expires_at < datetime.now(timezone.utc)
    ).delete()
    db.session.commit()
```

- [ ] **Step 5: Fill in `auth/jwt_callbacks.py`**

```python
# services/server/project/api/auth/jwt_callbacks.py
from flask import jsonify

from project.api.auth import sessions


def register_jwt_callbacks(jwt):
    @jwt.token_in_blocklist_loader
    def _check_revoked(jwt_header, jwt_payload):
        return sessions.is_revoked(jwt_payload.get("sid"))

    @jwt.revoked_token_loader
    def _revoked(jwt_header, jwt_payload):
        return jsonify({"type": "Authentication Error", "message": "Session expired or revoked"}), 401

    @jwt.unauthorized_loader
    def _missing(reason):
        return jsonify({"type": "Authentication Error", "message": reason}), 401

    @jwt.invalid_token_loader
    def _invalid(reason):
        return jsonify({"type": "Authentication Error", "message": reason}), 401

    @jwt.expired_token_loader
    def _expired(jwt_header, jwt_payload):
        return jsonify({"type": "Authentication Error", "message": "Token expired"}), 401
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd services/server && python3.11 -m pytest tests/test_sessions.py -v`
Expected: PASS.

- [ ] **Step 7: Lint & commit**

```bash
cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations
git add services/server/project/api/auth/models.py services/server/project/api/auth/sessions.py services/server/project/api/auth/jwt_callbacks.py services/server/tests/test_sessions.py
git commit -m "feat(auth): revocable UserSession store + JWT blocklist callbacks"
```

---

## Task 5: Roles domain — model, defaults seed, cached registry

**Files:**
- Create: `services/server/project/api/roles/models.py` (overwrites legacy `models.py`)
- Create: `services/server/project/api/roles/defaults.py`
- Create: `services/server/project/api/roles/registry.py`
- Test: `services/server/tests/test_roles.py`

> The legacy `roles` package still has `roles.py` + old `routes.py` at this point; they are removed in Task 11. Overwriting `models.py` here is safe because nothing new imports the old `Role` model, and the legacy blueprint is unregistered before the suite runs the roles routes (Task 11). To avoid a mixed-metadata clash during Tasks 5–10, also blank the legacy model now: replace the entire body of the old `models.py` with the new `RoleModel` below.

**Interfaces:**
- Produces: `RoleModel` (`roles` table: `id`, `name` unique, `description`, `permissions` JSON list, `is_system` bool, `created_by`, `created_at`, `updated_at`; `to_dict(user_count=None)`); `defaults.SYSADMIN_ROLE = "sysadmin"`, `defaults.DEFAULT_ROLES`, `defaults.ensure_default_roles()`; `registry.permission_map() -> dict[str,set]`, `registry.permissions_for(name) -> set`, `registry.invalidate()`.

- [ ] **Step 1: Write the failing test**

```python
# services/server/tests/test_roles.py
from project.api.roles import registry
from project.api.roles.defaults import SYSADMIN_ROLE
from project.api.roles.models import RoleModel


def test_default_roles_seeded(app):
    names = {r.name for r in RoleModel.query.all()}
    assert {"viewer", "analyst", SYSADMIN_ROLE} <= names

def test_sysadmin_is_protected_superuser(app):
    sysadmin = RoleModel.query.filter_by(name=SYSADMIN_ROLE).first()
    assert sysadmin.is_system is True
    assert sysadmin.permissions == ["*"]

def test_registry_resolves_permissions(app):
    assert "dataset:write" in registry.permissions_for("analyst")
    assert registry.permissions_for("viewer") == {
        "dataset:read", "model_config:read", "calibration:read",
        "forecast:read", "evaluation:read", "credit_risk:read",
    }
    assert registry.permissions_for("nonexistent") == set()

def test_registry_invalidate_picks_up_edits(app):
    from project import db
    role = RoleModel.query.filter_by(name="viewer").first()
    role.permissions = ["dataset:read", "dataset:write"]
    db.session.commit()
    registry.invalidate()
    assert "dataset:write" in registry.permissions_for("viewer")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/server && python3.11 -m pytest tests/test_roles.py -v`
Expected: FAIL — `project.api.roles.models.RoleModel` / `defaults` / `registry` missing.

- [ ] **Step 3: Write `roles/models.py`**

```python
# services/server/project/api/roles/models.py
from datetime import datetime, timezone

from project import db


class RoleModel(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(32), unique=True, nullable=False, index=True)
    description = db.Column(db.String(256), nullable=True)
    permissions = db.Column(db.JSON, nullable=False, default=list)
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    created_by = db.Column(db.String(64), nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_dict(self, user_count=None):
        d = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "permissions": list(self.permissions or []),
            "is_system": self.is_system,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if user_count is not None:
            d["user_count"] = user_count
        return d
```

- [ ] **Step 4: Write `roles/defaults.py`**

```python
# services/server/project/api/roles/defaults.py
from project import db
from project.api.roles.models import RoleModel

SYSADMIN_ROLE = "sysadmin"

DEFAULT_ROLES = [
    {
        "name": "sysadmin",
        "description": "Full administrative access. Built-in and protected.",
        "permissions": ["*"],
        "is_system": True,
    },
    {
        "name": "analyst",
        "description": "Runs the full modelling workflow.",
        "permissions": [
            "dataset:read", "dataset:write",
            "model_config:read", "model_config:write",
            "calibration:read", "calibration:write", "calibration:execute",
            "forecast:read", "forecast:write", "forecast:execute",
            "evaluation:read",
            "credit_risk:read", "credit_risk:write", "credit_risk:execute",
        ],
        "is_system": False,
    },
    {
        "name": "viewer",
        "description": "Read-only access to the modelling workflow.",
        "permissions": [
            "dataset:read", "model_config:read", "calibration:read",
            "forecast:read", "evaluation:read", "credit_risk:read",
        ],
        "is_system": False,
    },
]


def ensure_default_roles():
    """Idempotently insert the built-in roles. Safe to call on boot/seed/tests.

    Existing custom-edited roles are left alone; only the protected sysadmin row
    is kept authoritative (always all-perms, always is_system).
    """
    changed = False
    for spec in DEFAULT_ROLES:
        existing = RoleModel.query.filter_by(name=spec["name"]).first()
        if existing is None:
            db.session.add(RoleModel(**spec))
            changed = True
        elif spec["is_system"] and (
            list(existing.permissions or []) != spec["permissions"] or not existing.is_system
        ):
            existing.permissions = spec["permissions"]
            existing.is_system = True
            changed = True
    if changed:
        db.session.commit()
```

- [ ] **Step 5: Write `roles/registry.py`**

```python
# services/server/project/api/roles/registry.py
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
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd services/server && python3.11 -m pytest tests/test_roles.py -v`
Expected: PASS.

- [ ] **Step 7: Lint & commit**

```bash
cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations
git add services/server/project/api/roles/models.py services/server/project/api/roles/defaults.py services/server/project/api/roles/registry.py services/server/tests/test_roles.py
git commit -m "feat(rbac): DB-backed roles model, default seed, cached registry"
```

---

## Task 6: `require_perm` decorator (resolves via registry)

**Files:**
- Create: `services/server/project/api/auth/decorators.py`
- Test: `services/server/tests/test_rbac_enforcement.py` (decorator unit slice)

**Interfaces:**
- Consumes: `has_permission` (Task 1), `registry.permissions_for` (Task 5), `@jwt_required` (cookie mode, Task 3), session blocklist (Task 4).
- Produces: `require_perm(permission: str)` decorator; `current_role() -> str | None`; `current_permissions() -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# services/server/tests/test_rbac_enforcement.py
import pytest
from flask import Blueprint, jsonify

from project.api.auth.decorators import require_perm


@pytest.fixture()
def probe_app(app):
    bp = Blueprint("probe", __name__)

    @bp.post("/probe/exec")
    @require_perm("credit_risk:execute")
    def _exec():
        return jsonify(ok=True)

    app.register_blueprint(bp, url_prefix="/api")
    return app


@pytest.mark.parametrize("role,status", [("viewer", 403), ("analyst", 200), ("sysadmin", 200)])
def test_require_perm_gates_by_role(probe_app, make_user, role, status):
    client = probe_app.test_client()
    make_user(f"{role}@x.io", role)
    client.post("/api/auth/login", json={"email": f"{role}@x.io", "password": "Passw0rd!"})
    resp = client.post("/api/probe/exec")
    assert resp.status_code == status


def test_require_perm_requires_auth(probe_app):
    resp = probe_app.test_client().post("/api/probe/exec")
    assert resp.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/server && python3.11 -m pytest tests/test_rbac_enforcement.py -v`
Expected: FAIL — `decorators` module missing.

> **Ordering note:** these tests depend on `/api/auth/login` issuing cookies, which lands in Task 7. Mark both with `@pytest.mark.xfail(reason="needs login from Task 7")` if executing strictly task-by-task, and remove the xfail at the end of Task 7.

- [ ] **Step 3: Implement the decorator**

```python
# services/server/project/api/auth/decorators.py
from functools import wraps

from flask import abort
from flask_jwt_extended import get_jwt, jwt_required

from project.api.auth.permissions import has_permission
from project.api.roles.registry import permissions_for


def current_role():
    return get_jwt().get("role")


def current_permissions():
    return sorted(permissions_for(current_role()))


def require_perm(permission: str):
    def wrapper(fn):
        @wraps(fn)
        @jwt_required()
        def inner(*args, **kwargs):
            role = current_role()
            if not has_permission(permissions_for(role), permission):
                from project.api.auditlog.models import log_audit

                log_audit(
                    action="AccessDenied",
                    module="auth",
                    submodule="",
                    previous_data="",
                    new_data="",
                    description=f"Denied permission '{permission}'",
                    error_codes="403",
                    database_involved="",
                )
                abort(403, description="Access forbidden: insufficient privileges")
            return fn(*args, **kwargs)

        return inner

    return wrapper
```

- [ ] **Step 4: Lint & commit (test verified at end of Task 7)**

```bash
cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations
git add services/server/project/api/auth/decorators.py services/server/tests/test_rbac_enforcement.py
git commit -m "feat(auth): add require_perm decorator (registry-resolved)"
```

---

## Task 7: Rewrite auth routes (login / refresh / logout / me / change-password)

**Files:**
- Create: `services/server/project/api/auth/security.py`
- Rewrite: `services/server/project/api/auth/routes.py`
- Delete: `prevent_multiple_logins_per_user` from `services/server/project/api/auth/utils.py`
- Test: extend `services/server/tests/test_auth_routes.py`

**Interfaces:**
- Consumes: `User.authenticate` (existing), `sessions.*` (Task 4), `registry.permissions_for` (Task 5).
- Produces routes: `POST /api/auth/login`, `POST /api/auth/refresh`, `POST /api/auth/logout`, `GET /api/auth/me`, `POST /api/auth/change-password`. Login/me body: `{"user": {...}, "permissions": [...]}`; tokens delivered only as cookies.

- [ ] **Step 1: Write the failing tests**

```python
# append to services/server/tests/test_auth_routes.py
def test_login_sets_cookies_and_returns_permissions(client, make_user):
    make_user("a@x.io", "analyst")
    resp = client.post("/api/auth/login", json={"email": "a@x.io", "password": "Passw0rd!"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["user"]["role"] == "analyst"
    assert "dataset:write" in body["permissions"]
    assert any("access_token_cookie" in h for h in resp.headers.getlist("Set-Cookie"))
    assert "Passw0rd" not in resp.get_data(as_text=True)

def test_login_bad_password_401(client, make_user):
    make_user("a@x.io", "analyst")
    resp = client.post("/api/auth/login", json={"email": "a@x.io", "password": "wrong-pass1"})
    assert resp.status_code == 401

def test_me_requires_session(client):
    assert client.get("/api/auth/me").status_code == 401

def test_me_returns_identity_after_login(client, make_user):
    make_user("v@x.io", "viewer")
    client.post("/api/auth/login", json={"email": "v@x.io", "password": "Passw0rd!"})
    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    assert resp.get_json()["user"]["email"] == "v@x.io"
    assert "dataset:read" in resp.get_json()["permissions"]

def test_new_login_revokes_previous_session(client, make_user):
    make_user("u@x.io", "analyst")
    c1 = client
    c1.post("/api/auth/login", json={"email": "u@x.io", "password": "Passw0rd!"})
    c2 = c1.application.test_client()
    c2.post("/api/auth/login", json={"email": "u@x.io", "password": "Passw0rd!"})
    assert c1.get("/api/auth/me").status_code == 401
    assert c2.get("/api/auth/me").status_code == 200

def test_logout_revokes_session(client, make_user):
    make_user("u@x.io", "viewer")
    client.post("/api/auth/login", json={"email": "u@x.io", "password": "Passw0rd!"})
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/server && python3.11 -m pytest tests/test_auth_routes.py -v`
Expected: FAIL — new routes not implemented.

- [ ] **Step 3: Create `auth/security.py` (login lockout + password policy)**

```python
# services/server/project/api/auth/security.py
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
```

- [ ] **Step 4: Rewrite `auth/routes.py`**

```python
# services/server/project/api/auth/routes.py
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
    return (request.headers.get("X-Forwarded-For", request.remote_addr) or "").split(",")[0].strip()


def _issue_session(user) -> tuple:
    """Create a single fresh session; return (access_token, refresh_token, sid)."""
    sessions.revoke_all_for_user(user.email)  # single active session
    sid = uuid.uuid4().hex
    claims = {"role": user.role, "sid": sid}
    access = create_access_token(identity=user.email, additional_claims=claims)
    refresh = create_refresh_token(identity=user.email, additional_claims=claims)
    exp = datetime.fromtimestamp(decode_token(refresh)["exp"], tz=timezone.utc)
    sessions.create_session(sid, user.email, exp, _client_ip(), request.headers.get("User-Agent"))
    return access, refresh, sid


@auth.post("/login")
@validate_request(allowed_keys=["email", "password"])
def login():
    data = request.get_json() or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    ip = _client_ip()

    if security.is_locked(email, ip):
        return jsonify({"type": "Authentication Error", "message": "Account temporarily locked. Try again later."}), 429

    user = User.authenticate(email, password)
    if not user:
        security.record_failure(email, ip)
        log_audit(action="Login", user_email=email, module="uam", submodule="user",
                  description="User [$USER] failed to login", error_codes="401", database_involved="users")
        return jsonify({"type": "Authentication Error", "message": "Invalid username or password"}), 401

    security.clear_failures(email, ip)
    access, refresh, _ = _issue_session(user)
    resp = make_response(jsonify({"user": user.to_dict(), "permissions": sorted(permissions_for(user.role))}), 200)
    set_access_cookies(resp, access)
    set_refresh_cookies(resp, refresh)
    log_audit(action="Login", user_email=user.email, module="uam", submodule="user",
              description="User [$USER] logged in", error_codes="", database_involved="users")
    return resp


@auth.post("/refresh")
@jwt_required(refresh=True)
def refresh():
    identity = get_jwt_identity()
    sid = get_jwt().get("sid")
    if sessions.is_revoked(sid):
        return jsonify({"type": "Authentication Error", "message": "Session revoked"}), 401
    user = User.query.filter_by(email=identity).first()
    if not user or user.status != "active":
        return jsonify({"type": "Authentication Error", "message": "User inactive"}), 401
    access = create_access_token(identity=identity, additional_claims={"role": user.role, "sid": sid})
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
    log_audit(action="Logout", user_email=email, module="uam", submodule="user",
              description="User [$USER] logged out", error_codes="", database_involved="users")
    resp = make_response(jsonify({"logout": True}), 200)
    unset_jwt_cookies(resp)
    return resp


@auth.get("/me")
@jwt_required()
def me():
    user = User.query.filter_by(email=get_jwt_identity()).first()
    if not user:
        return jsonify({"type": "Authentication Error", "message": "Unknown user"}), 401
    return jsonify({"user": user.to_dict(), "permissions": sorted(permissions_for(user.role))}), 200


@auth.post("/change-password")
@jwt_required()
@validate_request(allowed_keys=["current_password", "new_password"])
def change_password():
    data = request.get_json() or {}
    user = User.query.filter_by(email=get_jwt_identity()).first()
    if not user or not bcrypt.check_password_hash(user.password, data.get("current_password", "")):
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
```

- [ ] **Step 5: Remove `prevent_multiple_logins_per_user`**

Delete that function from `services/server/project/api/auth/utils.py` (its single-session job is now the blocklist). Leave the rest of `utils.py` intact. (It is still imported by `users/routes.py`; Task 9 drops those usages — until then, leaving the import there is harmless only if the function exists, so **do Step 5 together with Task 9** or temporarily keep a no-op. Simplest: keep the import working by deferring this delete to Task 9, Step 3. If you delete it now, also do Task 9's decorator swap now.)

- [ ] **Step 6: Remove any `xfail` on the Task 6 decorator tests, then run the auth + rbac suites**

Run: `cd services/server && python3.11 -m pytest tests/test_auth_routes.py tests/test_rbac_enforcement.py -v`
Expected: PASS (login/me/logout/revocation + decorator gating).

- [ ] **Step 7: Lint & commit**

```bash
cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations
git add services/server/project/api/auth/ services/server/tests/test_auth_routes.py services/server/tests/test_rbac_enforcement.py
git commit -m "feat(auth): cookie-based login/refresh/logout/me with revocable single-session"
```

---

## Task 8: Roles CRUD API (`/api/roles`)

**Files:**
- Create: `services/server/project/api/roles/routes.py`
- Modify: `services/server/project/__init__.py` (register `roles_bp` at `/api/roles`; import `RoleModel` so `create_all` sees it)
- Test: `services/server/tests/test_roles_api.py`

**Interfaces:**
- Consumes: `require_perm` (Task 6), permission catalog helpers (Task 1), `registry` (Task 5), `RoleModel` (Task 5), `User` (existing).
- Produces routes: `GET /api/roles/catalog`, `GET /api/roles/`, `POST /api/roles/`, `PUT /api/roles/<name>`, `DELETE /api/roles/<name>`.

- [ ] **Step 1: Write the failing tests**

```python
# services/server/tests/test_roles_api.py
def _login(client, make_user, role):
    make_user(f"{role}@x.io", role)
    client.post("/api/auth/login", json={"email": f"{role}@x.io", "password": "Passw0rd!"})


def test_viewer_cannot_read_roles(client, make_user):
    _login(client, make_user, "viewer")
    assert client.get("/api/roles/").status_code == 403

def test_sysadmin_lists_roles_with_user_counts(client, make_user):
    _login(client, make_user, "sysadmin")
    resp = client.get("/api/roles/")
    assert resp.status_code == 200
    names = {r["name"] for r in resp.get_json()}
    assert {"viewer", "analyst", "sysadmin"} <= names

def test_catalog_endpoint(client, make_user):
    _login(client, make_user, "sysadmin")
    resp = client.get("/api/roles/catalog")
    assert resp.status_code == 200
    assert any(p["key"] == "credit_risk" for p in resp.get_json()["pages"])

def test_create_role(client, make_user):
    _login(client, make_user, "sysadmin")
    resp = client.post("/api/roles/", json={
        "name": "risk_lead", "description": "Risk lead",
        "permissions": ["dataset:read", "credit_risk:read", "credit_risk:execute"],
    })
    assert resp.status_code == 201
    assert resp.get_json()["permissions"] == ["credit_risk:execute", "credit_risk:read", "dataset:read"]

def test_create_role_rejects_wildcard(client, make_user):
    _login(client, make_user, "sysadmin")
    assert client.post("/api/roles/", json={"name": "god", "permissions": ["*"]}).status_code == 400

def test_create_role_rejects_unknown_permission(client, make_user):
    _login(client, make_user, "sysadmin")
    assert client.post("/api/roles/", json={"name": "x", "permissions": ["dataset:manage"]}).status_code == 400

def test_create_role_duplicate_name(client, make_user):
    _login(client, make_user, "sysadmin")
    assert client.post("/api/roles/", json={"name": "viewer", "permissions": []}).status_code == 409

def test_cannot_modify_system_role(client, make_user):
    _login(client, make_user, "sysadmin")
    assert client.put("/api/roles/sysadmin", json={"permissions": ["dataset:read"]}).status_code == 403
    assert client.delete("/api/roles/sysadmin").status_code == 403

def test_cannot_delete_role_in_use(client, make_user):
    _login(client, make_user, "sysadmin")
    make_user("someviewer@x.io", "viewer")
    resp = client.delete("/api/roles/viewer")
    assert resp.status_code == 409
    assert resp.get_json()["user_count"] >= 1

def test_update_role_permissions_takes_effect(client, make_user):
    _login(client, make_user, "sysadmin")
    client.post("/api/roles/", json={"name": "temp", "permissions": ["dataset:read"]})
    resp = client.put("/api/roles/temp", json={"permissions": ["dataset:read", "dataset:write"]})
    assert resp.status_code == 200
    assert "dataset:write" in resp.get_json()["permissions"]

def test_delete_unused_custom_role(client, make_user):
    _login(client, make_user, "sysadmin")
    client.post("/api/roles/", json={"name": "temp2", "permissions": ["dataset:read"]})
    assert client.delete("/api/roles/temp2").status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/server && python3.11 -m pytest tests/test_roles_api.py -v`
Expected: FAIL — `/api/roles/*` not registered.

- [ ] **Step 3: Write `roles/routes.py`**

```python
# services/server/project/api/roles/routes.py
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

roles_bp = Blueprint("roles", __name__)
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def _user_counts() -> dict:
    rows = db.session.query(User.role, db.func.count(User.email)).group_by(User.role).all()
    return {role: count for role, count in rows}


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
    return make_response(jsonify([r.to_dict(user_count=counts.get(r.name, 0)) for r in roles]), 200)


@roles_bp.post("/")
@require_perm("role:write")
def create_role():
    data = request.get_json() or {}
    name = (data.get("name") or "").strip().lower()
    description = (data.get("description") or "").strip()
    permissions = data.get("permissions") or []

    if not _NAME_RE.match(name):
        return make_response(jsonify({"message": "Role name must be lowercase letters/digits/underscores (2-32 chars)"}), 400)
    if RoleModel.query.filter_by(name=name).first():
        return make_response(jsonify({"message": f"Role '{name}' already exists"}), 409)
    bad = _reject_bad_permissions(permissions)
    if bad:
        return make_response(jsonify({"message": bad[0]}), bad[1])

    role = RoleModel(
        name=name,
        description=description,
        permissions=normalize_permissions(permissions),
        is_system=False,
        created_by=get_jwt_identity(),
    )
    db.session.add(role)
    db.session.commit()
    registry.invalidate()
    log_audit(action="Add", module="rbac", submodule="role", previous_data="", new_data=name,
              description=f"User [$USER] created role {name}", error_codes="", database_involved="roles")
    return make_response(jsonify(role.to_dict(user_count=0)), 201)


@roles_bp.put("/<string:name>")
@require_perm("role:write")
def update_role(name):
    role = RoleModel.query.filter_by(name=name).first()
    if not role:
        return make_response(jsonify({"message": "Role not found"}), 404)
    if role.is_system:
        return make_response(jsonify({"message": "Built-in roles cannot be modified"}), 403)

    data = request.get_json() or {}
    if "description" in data:
        role.description = (data.get("description") or "").strip()
    if "permissions" in data:
        permissions = data.get("permissions") or []
        bad = _reject_bad_permissions(permissions)
        if bad:
            return make_response(jsonify({"message": bad[0]}), bad[1])
        new_perms = normalize_permissions(permissions)
        # guard: don't let an admin strip role-management from the role they currently hold
        if role.name == current_role() and "role:write" not in new_perms:
            return make_response(jsonify({"message": "You cannot remove role-management permission from your own role"}), 400)
        role.permissions = new_perms

    db.session.commit()
    registry.invalidate()
    log_audit(action="Update", module="rbac", submodule="role", previous_data="", new_data=name,
              description=f"User [$USER] updated role {name}", error_codes="", database_involved="roles")
    return make_response(jsonify(role.to_dict()), 200)


@roles_bp.delete("/<string:name>")
@require_perm("role:write")
def delete_role(name):
    role = RoleModel.query.filter_by(name=name).first()
    if not role:
        return make_response(jsonify({"message": "Role not found"}), 404)
    if role.is_system:
        return make_response(jsonify({"message": "Built-in roles cannot be deleted"}), 403)
    in_use = User.query.filter_by(role=name).count()
    if in_use:
        return make_response(jsonify({"message": f"Role '{name}' is assigned to {in_use} user(s). Reassign them first.", "user_count": in_use}), 409)
    db.session.delete(role)
    db.session.commit()
    registry.invalidate()
    log_audit(action="Delete", module="rbac", submodule="role", previous_data=name, new_data="",
              description=f"User [$USER] deleted role {name}", error_codes="", database_involved="roles")
    return make_response(jsonify({"deleted": name}), 200)
```

- [ ] **Step 4: Register the blueprint in `__init__.py`**

Next to the other blueprint registrations add:

```python
    from project.api.roles.models import RoleModel  # noqa: F401  (ensure create_all sees it)
    from project.api.roles.routes import roles_bp

    app.register_blueprint(roles_bp, url_prefix="/api/roles")
```

(The legacy `role` blueprint registration is still present and is removed in Task 11; both can coexist briefly because the legacy one mounts at `/api/role` and this one at `/api/roles`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd services/server && python3.11 -m pytest tests/test_roles_api.py -v`
Expected: PASS.

- [ ] **Step 6: Lint & commit**

```bash
cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations
git add services/server/project/api/roles/routes.py services/server/project/__init__.py services/server/tests/test_roles_api.py
git commit -m "feat(rbac): roles CRUD API with catalog, protection and in-use guards"
```

---

## Task 9: Gate user-management endpoints (read/write split, DB role validation, CSV role column)

**Files:**
- Modify: `services/server/project/api/users/routes.py`
- Test: `services/server/tests/test_users_rbac.py`

**Interfaces:**
- Consumes: `require_perm` (Task 6), `sessions.revoke_all_for_user` (Task 4), `RoleModel` (Task 5).
- Produces: GET `/api/user/*` gated `user:read`; mutations gated `user:write`; role writes validated against existing DB roles; `add_batch` requires a valid `role` per row (no silent skips); changing a user's role revokes that user's sessions.

- [ ] **Step 1: Write the failing tests**

```python
# services/server/tests/test_users_rbac.py
def _login(client, make_user, role, email=None):
    email = email or f"{role}@x.io"
    make_user(email, role)
    client.post("/api/auth/login", json={"email": email, "password": "Passw0rd!"})


def test_viewer_cannot_list_users(client, make_user):
    _login(client, make_user, "viewer")
    assert client.get("/api/user/all").status_code == 403

def test_analyst_cannot_create_user(client, make_user):
    _login(client, make_user, "analyst")
    resp = client.post("/api/user/add", json={"email": "new@x.io", "password": "Passw0rd!", "role": "viewer"})
    assert resp.status_code == 403

def test_sysadmin_can_list_users(client, make_user):
    _login(client, make_user, "sysadmin")
    assert client.get("/api/user/all").status_code == 200

def test_invalid_role_rejected(client, make_user):
    _login(client, make_user, "sysadmin")
    make_user("t@x.io", "viewer")
    resp = client.put("/api/user/update/t@x.io", json={"role": "superuser"})
    assert resp.status_code == 400

def test_add_user_with_custom_role(client, make_user):
    _login(client, make_user, "sysadmin")
    client.post("/api/roles/", json={"name": "risk_lead", "permissions": ["credit_risk:read"]})
    resp = client.post("/api/user/add", json={"email": "rl@x.io", "password": "Passw0rd!", "role": "risk_lead"})
    assert resp.status_code == 201

def test_add_batch_rejects_invalid_role(client, make_user):
    _login(client, make_user, "sysadmin")
    resp = client.post("/api/user/add_batch", json={"users": [
        {"email": "ok@x.io", "password": "Passw0rd!", "role": "viewer", "name": "Ok"},
        {"email": "bad@x.io", "password": "Passw0rd!", "role": "nope", "name": "Bad"},
    ]})
    assert resp.status_code == 400
    assert "bad@x.io" in resp.get_data(as_text=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/server && python3.11 -m pytest tests/test_users_rbac.py -v`
Expected: FAIL — endpoints currently return 2xx for any authenticated user; bad roles silently skipped.

- [ ] **Step 3: Gate the routes + validate roles + fix batch**

In `services/server/project/api/users/routes.py`:

1. Replace the auth imports. Remove `from flask_jwt_extended import jwt_required` and `from project.api.auth.utils import prevent_multiple_logins_per_user`; add:

```python
from project.api.auth.decorators import require_perm
from project.api.auth import sessions
from project.api.roles.models import RoleModel
```

2. On every route, **remove** the `@jwt_required()` and `@prevent_multiple_logins_per_user()` decorators and put a single permission gate directly under `@user.route(...)`: GET routes (`/all`, `/is_local_system_admin/...`, `/id/...`, `/email/...`) → `@require_perm("user:read")`; mutating routes (`/add`, `/add_batch`, `/update/...`, `/updates`, `/delete/...`) → `@require_perm("user:write")`.

3. Add a role-validation helper near the top of the module:

```python
def _role_exists(role: str) -> bool:
    return bool(role) and RoleModel.query.filter_by(name=role).first() is not None
```

4. In `add_user` (`/add`): after the `if not email or not password or not role:` check, add:

```python
        if not _role_exists(role):
            raise ValueError(f"Unknown role '{role}'")
```

5. In `update_user` (`/update/<email>`) and each entry of `update_users` (`/updates`): where role changes (`if role and role != user.role:`), validate first and revoke sessions after commit:

```python
        if role and role != user.role:
            if not _role_exists(role):
                raise Exception(f"Unknown role '{role}'")
            previous_data["role"] = user.role
            new_data["role"] = role
            user.role = role
            # (after db.session.commit() below)
            sessions.revoke_all_for_user(user.email)
```

Place the `sessions.revoke_all_for_user(user.email)` call immediately after the corresponding `db.session.commit()` in each handler, guarded by `if "role" in new_data:`.

6. Rewrite `add_multi_users` (`/add_batch`) to validate every row and reject the batch with row-level errors instead of silently skipping:

```python
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
                errors.append(f"row {idx + 1} ({email}): unknown role '{user_data.get('role')}'")
        if errors:
            return make_response(jsonify({"message": "Import rejected", "errors": errors}), 400)

        for user_data in users:
            email = user_data.get("email")
            if User.query.filter_by(email=email).first():
                continue
            db.session.add(User(
                email=email,
                password=user_data.get("password"),
                role=user_data.get("role"),
                name=user_data.get("name"),
                status=user_data.get("status"),
                registered_on=valid_date(user_data.get("registeredOn", datetime.now(timezone.utc))),
            ))
        db.session.commit()

        log_audit(action="Add", module="uam", submodule="user", previous_data="", new_data="",
                  description="User [$USER] added multiple users", error_codes="", database_involved="users")
        return make_response(jsonify({"message": "Users added"}), 201)
    except Exception as e:
        db.session.rollback()
        log_audit(action="Add", module="uam", submodule="user", previous_data="", new_data="",
                  description=f"User [$USER] failed to add multiple users. Error: {str(e)}",
                  error_codes="500", database_involved="users")
        return make_response(jsonify({"message": str(e)}), 500)
```

7. Now complete Task 7 Step 5: delete `prevent_multiple_logins_per_user` from `auth/utils.py` (no remaining importers).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd services/server && python3.11 -m pytest tests/test_users_rbac.py -v`
Expected: PASS.

- [ ] **Step 5: Lint & commit**

```bash
cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations
git add services/server/project/api/users/routes.py services/server/project/api/auth/utils.py services/server/tests/test_users_rbac.py
git commit -m "feat(auth): gate user mgmt; validate roles against DB; strict batch import"
```

---

## Task 10: Apply `require_perm` across all domain blueprints (endpoint matrix)

**Files:**
- Modify: `datasets/routes.py`, `model_configs/routes.py`, `calibrations/routes.py`, `forecasts/routes.py`, `forecast_runs/routes.py`, `evaluations/routes.py`, `credit_risk/routes.py`, `auditlog/routes.py`
- Test: extend `services/server/tests/test_rbac_enforcement.py` with a real-endpoint matrix.

**Interfaces:**
- Consumes: `require_perm` (Task 6). Uses the **Endpoint → permission matrix** table above.

- [ ] **Step 1: Write the failing matrix test**

```python
# append to services/server/tests/test_rbac_enforcement.py
import pytest

# (method, path, viewer_status, analyst_status)
MATRIX = [
    ("get",  "/api/datasets/",        200, 200),
    ("post", "/api/datasets/upload",  403, 400),   # 400 = passed RBAC, failed on missing file
    ("post", "/api/credit-risk/runs", 403, 400),   # 400 = passed RBAC, bad body
    ("get",  "/api/log/",             403, 403),   # auditlog read = role-gated, neither has it
]


def _login_as(app, email, role):
    from project import db
    from project.api.users.models import User
    u = User(email=email, password="Passw0rd!", role=role, name=email)
    u.status = "active"
    db.session.add(u); db.session.commit()
    c = app.test_client()
    c.post("/api/auth/login", json={"email": email, "password": "Passw0rd!"})
    return c


@pytest.mark.parametrize("method,path,viewer_status,analyst_status", MATRIX)
def test_endpoint_matrix(app, method, path, viewer_status, analyst_status):
    cv = _login_as(app, "mv@x.io", "viewer")
    assert getattr(cv, method)(path).status_code == viewer_status
    ca = _login_as(app, "ma@x.io", "analyst")
    assert getattr(ca, method)(path).status_code == analyst_status
```

> Adjust the `auditlog` list-route path if it differs from `/api/log/`. The 400 expectations confirm the request got **past** RBAC into the handler. Extend `MATRIX` with one representative row per blueprint as you gate it.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/server && python3.11 -m pytest tests/test_rbac_enforcement.py::test_endpoint_matrix -v`
Expected: FAIL — viewer currently gets 2xx on writes; auditlog open to all.

- [ ] **Step 3: Add decorators per the matrix**

For each blueprint add `from project.api.auth.decorators import require_perm` and place `@require_perm("<perm>")` under each route decorator, following the matrix (GET → `<domain>:read`; create/edit/delete → `<domain>:write`; run/compute → `<domain>:execute`). Examples:

```python
# datasets/routes.py
@datasets.get("/")
@require_perm("dataset:read")
def list_datasets(): ...

@datasets.post("/upload")
@require_perm("dataset:write")
def upload_dataset(): ...

@datasets.post("/query")
@require_perm("dataset:write")
def query_dataset(): ...
```

```python
# credit_risk/routes.py — examples
@credit_risk.get("/runs")
@require_perm("credit_risk:read")
def list_runs(): ...

@credit_risk.post("/runs")
@require_perm("credit_risk:execute")
def create_run(): ...

@credit_risk.delete("/runs/<cr_run_id>")
@require_perm("credit_risk:write")
def delete_run(): ...

@credit_risk.post("/kmv")
@require_perm("credit_risk:read")
def compute_kmv(): ...
```

```python
# auditlog/routes.py
@auditlog.get("/")
@require_perm("auditlog:read")
def list_logs(): ...
```

Replace any existing bare `@jwt_required()` on these routes with `@require_perm(...)` (it already enforces auth). Work through every route in each blueprint.

- [ ] **Step 4: Run the full backend suite**

Run: `cd services/server && python3.11 -m pytest tests/ -v`
Expected: PASS (matrix + all prior suites; `test_credit_risk.py` still green).

- [ ] **Step 5: Lint & commit**

```bash
cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations
git add services/server/project/api services/server/tests/test_rbac_enforcement.py
git commit -m "feat(auth): enforce per-endpoint permissions across all blueprints"
```

---

## Task 11: Remove legacy roles system + register/migrate DB

**Files:**
- Delete: legacy `services/server/project/api/roles/roles.py` and the legacy contents of `routes.py` (the new `routes.py` from Task 8 stays)
- Modify: `services/server/project/__init__.py` (drop legacy `role` blueprint import/registration + `ActiveSession` import)
- Modify: `services/server/manage.py` (`seed_db`)
- Create: Alembic migration
- Test: `services/server/tests/test_auth_routes.py` (legacy gone)

**Interfaces:**
- Produces: no `/api/role/*` (singular) routes; legacy `roles` + `active_session` tables dropped; new `roles` (+ seeded rows) and `user_sessions` created; `users.role` normalized.

- [ ] **Step 1: Write the failing test**

```python
# append to services/server/tests/test_auth_routes.py
def test_legacy_role_endpoints_gone(client, make_user):
    make_user("s@x.io", "sysadmin")
    client.post("/api/auth/login", json={"email": "s@x.io", "password": "Passw0rd!"})
    assert client.get("/api/role/all").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/server && python3.11 -m pytest tests/test_auth_routes.py::test_legacy_role_endpoints_gone -v`
Expected: FAIL — `/api/role/all` still registered.

- [ ] **Step 3: Remove the legacy blueprint and model wiring**

In `services/server/project/__init__.py`: delete the legacy `from project.api.roles.routes import role` import (note: this differs from the new `roles_bp`), the legacy `app.register_blueprint(role, ...)` line, and `from project.api.auth.models import ActiveSession` (replace with `from project.api.auth.models import UserSession  # noqa: F401`). Then remove the legacy module:

```bash
git rm services/server/project/api/roles/roles.py
```

Grep for stragglers:

```bash
grep -rn "roles_required\|roles_satisfied\|load_roles_from_db\|ActiveSession\|prevent_multiple_logins\|import role\b" services/server/project
```

Expected after edits: no hits outside migrations and outside the new `roles_bp` registration.

- [ ] **Step 4: Update `seed_db` in `manage.py`**

```python
@cli.command("seed_db")
def seed_db():
    import os

    from project.api.roles.defaults import ensure_default_roles
    from project.api.users.models import User

    ensure_default_roles()
    admin_email = os.getenv("SEED_ADMIN_EMAIL", "admin@crest.local")
    admin_pw = os.getenv("SEED_ADMIN_PASSWORD")
    if not admin_pw:
        raise SystemExit("SEED_ADMIN_PASSWORD env var is required to seed the admin user")
    if not User.query.filter_by(email=admin_email).first():
        db.session.add(User(email=admin_email, password=admin_pw, role="sysadmin", name="Administrator"))
        db.session.commit()
```

- [ ] **Step 5: Generate & edit the migration (real DB only)**

With the MSSQL stack running and `flask db upgrade` current:

```bash
cd services/server && flask --app manage.py db migrate -m "auth rebuild: new roles+user_sessions, drop legacy roles+active_session, normalize role"
```

Then **edit the generated migration**. `upgrade()` must perform, in order:

```python
import json
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.drop_table("active_session")
    op.drop_table("roles")  # legacy ESG-module schema

    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("description", sa.String(length=256), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_by", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_roles_name"), "roles", ["name"], unique=True)

    now = datetime.now(timezone.utc)
    roles_tbl = sa.table(
        "roles",
        sa.column("name", sa.String), sa.column("description", sa.String),
        sa.column("permissions", sa.JSON), sa.column("is_system", sa.Boolean),
        sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(roles_tbl, [
        {"name": "sysadmin", "description": "Full administrative access. Built-in and protected.",
         "permissions": ["*"], "is_system": True, "created_at": now, "updated_at": now},
        {"name": "analyst", "description": "Runs the full modelling workflow.",
         "permissions": ["dataset:read","dataset:write","model_config:read","model_config:write",
                          "calibration:read","calibration:write","calibration:execute","forecast:read",
                          "forecast:write","forecast:execute","evaluation:read","credit_risk:read",
                          "credit_risk:write","credit_risk:execute"],
         "is_system": False, "created_at": now, "updated_at": now},
        {"name": "viewer", "description": "Read-only access to the modelling workflow.",
         "permissions": ["dataset:read","model_config:read","calibration:read","forecast:read",
                         "evaluation:read","credit_risk:read"],
         "is_system": False, "created_at": now, "updated_at": now},
    ])

    op.create_table(
        "user_sessions",
        sa.Column("sid", sa.String(length=36), nullable=False),
        sa.Column("user_email", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(["user_email"], ["users.email"]),
        sa.PrimaryKeyConstraint("sid"),
    )
    op.create_index(op.f("ix_user_sessions_user_email"), "user_sessions", ["user_email"])

    op.execute("UPDATE users SET role='sysadmin' WHERE role IN ('admin','administrator')")
    op.execute("UPDATE users SET role='viewer' WHERE role NOT IN ('viewer','analyst','sysadmin')")
```

Write the inverse in `downgrade()` (drop `user_sessions`, drop new `roles`, recreate the legacy tables as they were). Review the autogenerated body — do not trust it blindly; in particular ensure it did not also try to drop/recreate unrelated tables.

- [ ] **Step 6: Run the full suite + verify migration applies**

Run: `cd services/server && python3.11 -m pytest tests/ -v` → PASS.
Run (with DB up): `cd services/server && flask --app manage.py db upgrade` → completes; new `roles` (3 seeded rows) + `user_sessions` exist, legacy `roles`/`active_session` gone.

- [ ] **Step 7: Lint & commit**

```bash
cd services/server && ruff check . --exclude migrations --fix && ruff format . --exclude migrations
git add -A services/server
git commit -m "refactor(auth): remove legacy role matrix; migrate to runtime roles + user_sessions"
```

---

## Task 12: Frontend — httpClient cookie mode + CSRF + refresh

**Files:**
- Rewrite: `services/client/src/api/httpClient.js`
- Modify: `services/client/src/api/authAPI.js`
- Create: `services/client/src/utils/cookies.js`
- Test: `services/client/vitest.config.js`, `services/client/src/api/__tests__/httpClient.spec.js`

**Interfaces:**
- Produces: `httpClient` (axios, `withCredentials: true`, injects `X-CSRF-TOKEN`, refreshes on 401 via `/auth/refresh`); `getCookie(name)`; `authAPI.login/refresh/logout/me/changePassword`.

- [ ] **Step 1: Add Vitest config + a cookie helper, and write the failing test**

```js
// services/client/vitest.config.js
import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  test: { environment: 'jsdom', globals: true }
})
```

```js
// services/client/src/utils/cookies.js
export function getCookie(name) {
  const match = document.cookie.match(new RegExp('(^|; )' + name + '=([^;]*)'))
  return match ? decodeURIComponent(match[2]) : null
}
```

```js
// services/client/src/api/__tests__/httpClient.spec.js
import { describe, it, expect, beforeEach } from 'vitest'
import { getCookie } from '@/utils/cookies'

describe('getCookie', () => {
  beforeEach(() => { document.cookie = 'csrf_access_token=abc123; path=/' })
  it('reads a cookie value', () => { expect(getCookie('csrf_access_token')).toBe('abc123') })
  it('returns null for a missing cookie', () => { expect(getCookie('nope')).toBeNull() })
})
```

Add to `services/client/package.json` devDependencies (then `npm install`): `"vitest"`, `"@vitejs/plugin-vue"`, `"jsdom"`, `"@vue/test-utils"`; and script `"test": "vitest run"`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/client && npx vitest run src/api/__tests__/httpClient.spec.js`
Expected: FAIL — `@/utils/cookies` missing → then PASS once the file above is saved.

- [ ] **Step 3: Rewrite `httpClient.js`**

```js
// services/client/src/api/httpClient.js
import axios from 'axios'
import store from '@/store'
import router from '@/router'
import { getCookie } from '@/utils/cookies'

const API_URL = (import.meta.env.VITE_API_URL || '') + '/api'

export const httpClient = axios.create({ baseURL: API_URL, withCredentials: true })

// Attach CSRF header for state-changing requests (double-submit cookie).
httpClient.interceptors.request.use((config) => {
  const method = (config.method || 'get').toLowerCase()
  if (method !== 'get' && method !== 'head' && method !== 'options') {
    const isRefresh = (config.url || '').includes('/auth/refresh')
    const token = getCookie(isRefresh ? 'csrf_refresh_token' : 'csrf_access_token')
    if (token) config.headers['X-CSRF-TOKEN'] = token
  }
  return config
})

let isRefreshing = false
let subscribers = []
const onRefreshed = () => { subscribers.forEach((cb) => cb()); subscribers = [] }

httpClient.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config
    const status = error.response?.status
    const url = original?.url || ''
    if (status !== 401 || original._retry || url.includes('/auth/refresh') || url.includes('/auth/login')) {
      return Promise.reject(error)
    }
    if (isRefreshing) {
      return new Promise((resolve) => subscribers.push(() => { original._retry = true; resolve(httpClient(original)) }))
    }
    original._retry = true
    isRefreshing = true
    try {
      await httpClient.post('/auth/refresh')
      isRefreshing = false
      onRefreshed()
      return httpClient(original)
    } catch (e) {
      isRefreshing = false
      subscribers = []
      store.dispatch('logout', true)
      router.push({ name: 'login' })
      return Promise.reject(e)
    }
  }
)

export default httpClient
```

> Remove the old `setAuthHeader` export and any `import { setAuthHeader }` usages in `api/*.js` (Task 16 cleans those call sites). For this task, update `authAPI.js` only.

```js
// services/client/src/api/authAPI.js
import httpClient from '@/api/httpClient'

const authAPI = {
  login: (credentials) => httpClient.post('/auth/login', credentials),
  refresh: () => httpClient.post('/auth/refresh'),
  logout: () => httpClient.post('/auth/logout'),
  me: () => httpClient.get('/auth/me'),
  changePassword: (payload) => httpClient.post('/auth/change-password', payload)
}
export default authAPI
```

- [ ] **Step 4: Run the cookie test to verify it passes**

Run: `cd services/client && npx vitest run src/api/__tests__/httpClient.spec.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/client/vitest.config.js services/client/package.json services/client/src/utils/cookies.js services/client/src/api/httpClient.js services/client/src/api/authAPI.js services/client/src/api/__tests__/httpClient.spec.js
git commit -m "feat(web): cookie-based httpClient with CSRF + silent refresh"
```

---

## Task 13: Frontend — auth store (`/me` bootstrap, permissions) + `can()` + `v-can`

**Files:**
- Rewrite: `services/client/src/store/index.js` (auth slice), `services/client/src/store/actions/authActions.js`
- Create: `services/client/src/utils/permissions.js`, `services/client/src/directives/can.js`
- Modify: `services/client/src/main.js` (register `v-can`; bootstrap `/me`)
- Test: `services/client/src/utils/__tests__/permissions.spec.js`

**Interfaces:**
- Produces: store state `currentUser`, `permissions`; getters `isAuthenticated`, `can`; actions `login`, `logout`, `fetchMe`; `can(permissions, perm)` util (membership + `*`); `v-can` directive.

- [ ] **Step 1: Write the failing test**

```js
// services/client/src/utils/__tests__/permissions.spec.js
import { describe, it, expect } from 'vitest'
import { can } from '@/utils/permissions'

describe('can', () => {
  it('grants only explicitly-held permissions', () => {
    const p = ['dataset:read', 'model_config:read', 'credit_risk:read']
    expect(can(p, 'dataset:read')).toBe(true)
    expect(can(p, 'dataset:write')).toBe(false)
    expect(can(p, 'user:read')).toBe(false)
  })
  it('analyst can execute runs it holds', () => {
    expect(can(['credit_risk:read', 'credit_risk:execute'], 'credit_risk:execute')).toBe(true)
  })
  it('superuser wildcard allows everything', () => {
    expect(can(['*'], 'user:write')).toBe(true)
    expect(can(['*'], 'role:write')).toBe(true)
  })
  it('empty permissions deny', () => {
    expect(can([], 'dataset:read')).toBe(false)
    expect(can(null, 'dataset:read')).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/client && npx vitest run src/utils/__tests__/permissions.spec.js`
Expected: FAIL — `@/utils/permissions` missing.

- [ ] **Step 3: Implement `permissions.js` (mirror of backend resolver)**

```js
// services/client/src/utils/permissions.js
export function can(permissions, permission) {
  if (!permissions || permissions.length === 0) return false
  if (permissions.includes('*')) return true
  return permissions.includes(permission)
}
```

- [ ] **Step 4: Rewrite the auth store slice**

```js
// services/client/src/store/actions/authActions.js
import { authAPI } from '@/api'

export const authActions = {
  async login(context, credentials) {
    const { data } = await authAPI.login(credentials)
    context.commit('setAuth', { user: data.user, permissions: data.permissions })
    return data
  },
  async fetchMe(context) {
    try {
      const { data } = await authAPI.me()
      context.commit('setAuth', { user: data.user, permissions: data.permissions })
      return true
    } catch {
      context.commit('clearAuth')
      return false
    }
  },
  async logout(context, skipBackend = false) {
    if (!skipBackend) { try { await authAPI.logout() } catch { /* ignore */ } }
    context.commit('clearAuth')
  }
}
```

In `store/index.js`: set `state = { currentUser: null, permissions: [] }` (remove `jwt`, `roles`, `ROLES_PER_MODULE`). Remove `vuex-persistedstate` for the auth slice (cookies are the source of truth). Replace getters/mutations:

```js
import { can as canPerm } from '@/utils/permissions'

const getters = {
  isAuthenticated: (state) => !!state.currentUser,
  getCurrentUser: (state) => state.currentUser,
  can: (state) => (permission) => canPerm(state.permissions, permission)
}
const mutations = {
  setAuth(state, { user, permissions }) { state.currentUser = user; state.permissions = permissions || [] },
  clearAuth(state) { state.currentUser = null; state.permissions = [] }
}
```

Remove `getModulesByRole`, `setRoles`, `setLoginData`, `setAccessToken`, and the `roleActions` registration in `store/actions/index.js`.

- [ ] **Step 5: Register `v-can` and bootstrap `/me`**

```js
// services/client/src/directives/can.js
import store from '@/store'
export const can = {
  mounted(el, binding) {
    if (!store.getters.can(binding.value)) el.parentNode && el.parentNode.removeChild(el)
  }
}
```

In `main.js`: `import { can } from '@/directives/can'` then `app.directive('can', can)`. Before mounting, bootstrap the session:

```js
store.dispatch('fetchMe').finally(() => app.mount('#app'))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd services/client && npx vitest run`
Expected: PASS (permissions + cookies specs).

- [ ] **Step 7: Commit**

```bash
git add services/client/src/store services/client/src/utils/permissions.js services/client/src/directives/can.js services/client/src/main.js services/client/src/utils/__tests__/permissions.spec.js
git commit -m "feat(web): permission-driven auth store with /me bootstrap and v-can"
```

---

## Task 14: Frontend — menu filtering + router guard (incl. role-management route)

**Files:**
- Modify: `services/client/src/layout/AppMenu.vue`
- Modify: `services/client/src/router/index.js`

**Interfaces:**
- Consumes: store getter `can`, `fetchMe`. Produces: menu items filtered by capability; routes guarded by `requiresAuth` + optional `requiresPerm`; a new `role-management` route.

- [ ] **Step 1: Map menu modules to permissions and filter**

In `AppMenu.vue`, give each item a `perm` and filter `model` by `can()`. Replace `onMounted(() => { filteredModel.value = model })` with a computed:

```js
import { computed } from 'vue'
import { useStore } from 'vuex'
const store = useStore()
const can = (p) => store.getters.can(p)
// add perm to items, e.g. { label: 'Datasets', to: { name: 'datasets' }, perm: 'dataset:read' }
//   System group: UAM -> 'user:read'; Role Management -> 'role:read'; Audit Logs -> 'auditlog:read'
const filteredModel = computed(() =>
  model
    .map((group) => ({ ...group, items: group.items.filter((it) => !it.perm || can(it.perm)) }))
    .filter((group) => group.items.length > 0)
)
```

Map: Datasets→`dataset:read`; Model Catalog/Configurations→`model_config:read`; New/Jobs Calibration→`calibration:read`; Forecast→`forecast:read`; Credit Risk items→`credit_risk:read`; UAM→`user:read`; **Role Management→`role:read`**; Audit Logs→`auditlog:read`. Add the Role Management item to the System group: `{ label: 'Role Management', icon: 'pi pi-shield', to: { name: 'role-management' }, perm: 'role:read' }`.

- [ ] **Step 2: Add the role-management route + permission guard**

In `router/index.js`, add the route (lazy-loaded) and `meta.requiresPerm` on sensitive routes:

```js
{
  path: '/role-management',
  name: 'role-management',
  component: () => import('@/views/admin/RoleManagement.vue'),
  meta: { requiresAuth: true, requiresPerm: 'role:read' }
}
```

Set `uam` → `meta.requiresPerm: 'user:read'`, `log` → `'auditlog:read'`. Update `beforeEach`:

```js
router.beforeEach(async (to, from, next) => {
  const needsAuth = to.matched.some((r) => r.meta.requiresAuth)
  if (!needsAuth) return next()
  if (!store.getters.isAuthenticated) {
    const ok = await store.dispatch('fetchMe')
    if (!ok) return next({ name: 'login', query: { redirect: to.fullPath } })
  }
  const permRoute = to.matched.find((r) => r.meta.requiresPerm)
  if (permRoute && !store.getters.can(permRoute.meta.requiresPerm)) {
    return next({ name: 'accessDenied' })
  }
  return next()
})
```

(Removes the old `isValidJwt`/token-based guard logic. If an `accessDenied` route does not exist, route to the dashboard/home name instead.)

- [ ] **Step 3: Build to ensure no import errors**

Run: `cd services/client && npm run build`
Expected: build succeeds (the `RoleManagement.vue` import resolves once Task 15 creates it — do Task 15 before this build, or stub the file).

- [ ] **Step 4: Commit**

```bash
git add services/client/src/layout/AppMenu.vue services/client/src/router/index.js
git commit -m "feat(web): capability-filtered menu, route perm guard, role-mgmt route"
```

---

## Task 15: Frontend — Role Management page (list + permission matrix)

**Files:**
- Create: `services/client/src/api/roleAPI.js`
- Create: `services/client/src/views/admin/RoleManagement.vue`
- Modify: `services/client/src/api/index.js` (export `roleAPI`)

**Interfaces:**
- Consumes: `httpClient` (Task 12), catalog + roles endpoints (Task 8), `can` getter (Task 13).
- Produces: `roleAPI.list/catalog/create/update/remove`; a page that lists roles and edits each role's read/write/execute matrix.

- [ ] **Step 1: Create the API wrapper**

```js
// services/client/src/api/roleAPI.js
import httpClient from '@/api/httpClient'

const roleAPI = {
  list: () => httpClient.get('/roles/'),
  catalog: () => httpClient.get('/roles/catalog'),
  create: (payload) => httpClient.post('/roles/', payload),
  update: (name, payload) => httpClient.put(`/roles/${name}`, payload),
  remove: (name) => httpClient.delete(`/roles/${name}`)
}
export default roleAPI
```

In `services/client/src/api/index.js`, add `export { default as roleAPI } from '@/api/roleAPI'` (match the file's existing export style).

- [ ] **Step 2: Create `RoleManagement.vue`**

```vue
<!-- services/client/src/views/admin/RoleManagement.vue -->
<template>
  <div class="p-5 mx-auto" style="max-width: 1400px">
    <header class="flex align-items-end justify-content-between mb-5 flex-wrap gap-3">
      <div>
        <h1 class="text-3xl font-semibold m-0 tracking-tight">Role Management</h1>
        <p class="text-color-secondary text-sm m-0 mt-1">Define roles and the pages each role can read, write, or execute.</p>
      </div>
      <Button v-can="'role:write'" icon="pi pi-plus" label="New Role" @click="openCreate" />
    </header>

    <div class="panel">
      <DataTable :value="roles" dataKey="name" class="bare-table-inner">
        <Column field="name" header="Role" sortable style="min-width: 12rem">
          <template #body="{ data }">
            <span class="font-medium">{{ data.name }}</span>
            <Tag v-if="data.is_system" value="built-in" severity="warning" class="ml-2" />
          </template>
        </Column>
        <Column field="description" header="Description" style="min-width: 18rem" />
        <Column field="user_count" header="Users" style="width: 7rem" />
        <Column :exportable="false" style="width: 9rem">
          <template #body="{ data }">
            <div class="flex gap-1 justify-content-end">
              <Button icon="pi pi-pencil" text rounded size="small" severity="secondary"
                      :disabled="data.is_system || !canWrite" @click="openEdit(data)" />
              <Button icon="pi pi-trash" text rounded size="small" severity="danger"
                      :disabled="data.is_system || !canWrite" @click="confirmDelete(data)" />
            </div>
          </template>
        </Column>
      </DataTable>
    </div>

    <Dialog v-model:visible="showDialog" :style="{ width: '640px' }" :header="editing ? 'Edit Role' : 'New Role'" modal class="p-fluid">
      <div class="field">
        <label class="block text-900 font-medium mb-2">Name</label>
        <InputText v-model.trim="form.name" :disabled="editing" placeholder="e.g. risk_lead" />
        <small class="text-color-secondary">Lowercase letters, digits, underscores.</small>
      </div>
      <div class="field">
        <label class="block text-900 font-medium mb-2">Description</label>
        <InputText v-model.trim="form.description" />
      </div>

      <label class="block text-900 font-medium mb-2">Permissions</label>
      <table class="perm-matrix">
        <thead>
          <tr><th>Page</th><th>Read</th><th>Write</th><th>Execute</th></tr>
        </thead>
        <tbody>
          <tr v-for="page in catalog" :key="page.key">
            <td>{{ page.label }}</td>
            <td v-for="action in ['read','write','execute']" :key="action">
              <Checkbox v-if="hasAction(page, action)" :binary="true"
                        :modelValue="isChecked(page.key, action)"
                        @update:modelValue="(v) => toggle(page.key, action, v)" />
              <span v-else class="text-color-secondary">—</span>
            </td>
          </tr>
        </tbody>
      </table>

      <template #footer>
        <Button label="Cancel" icon="pi pi-times" text @click="showDialog = false" />
        <Button label="Save" icon="pi pi-check" text @click="save" />
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useStore } from 'vuex'
import { useToast } from 'primevue/usetoast'
import { useConfirm } from 'primevue/useconfirm'
import { roleAPI } from '@/api'

const store = useStore()
const toast = useToast()
const confirm = useConfirm()

const roles = ref([])
const catalog = ref([])
const showDialog = ref(false)
const editing = ref(false)
const form = reactive({ name: '', description: '', permissions: new Set() })

const canWrite = computed(() => store.getters.can('role:write'))

const load = async () => {
  const [r, c] = await Promise.all([roleAPI.list(), roleAPI.catalog()])
  roles.value = r.data
  catalog.value = c.data.pages
}

onMounted(load)

const hasAction = (page, action) => page.actions.some((a) => a.key === action)
const isChecked = (pageKey, action) => form.permissions.has(`${pageKey}:${action}`)
const toggle = (pageKey, action, value) => {
  const key = `${pageKey}:${action}`
  if (value) form.permissions.add(key)
  else form.permissions.delete(key)
}

const openCreate = () => {
  editing.value = false
  form.name = ''; form.description = ''; form.permissions = new Set()
  showDialog.value = true
}
const openEdit = (role) => {
  editing.value = true
  form.name = role.name; form.description = role.description || ''
  form.permissions = new Set(role.permissions)
  showDialog.value = true
}

const save = async () => {
  const payload = { name: form.name, description: form.description, permissions: [...form.permissions] }
  try {
    if (editing.value) await roleAPI.update(form.name, { description: payload.description, permissions: payload.permissions })
    else await roleAPI.create(payload)
    showDialog.value = false
    await load()
    toast.add({ severity: 'success', summary: 'Saved', detail: `Role ${form.name} saved.`, life: 2500 })
  } catch (err) {
    toast.add({ severity: 'error', summary: 'Error', detail: err.response?.data?.message || err.message, life: 5000 })
  }
}

const confirmDelete = (role) => {
  confirm.require({
    message: `Delete role "${role.name}"?`,
    header: 'Confirm',
    icon: 'pi pi-exclamation-triangle',
    accept: async () => {
      try {
        await roleAPI.remove(role.name)
        await load()
        toast.add({ severity: 'info', summary: 'Deleted', detail: `Role ${role.name} deleted.`, life: 2500 })
      } catch (err) {
        toast.add({ severity: 'error', summary: 'Error', detail: err.response?.data?.message || err.message, life: 6000 })
      }
    }
  })
}
</script>

<style scoped>
.panel { background: var(--surface-card); border: 1px solid var(--surface-border); border-radius: 12px; padding: 1.25rem; }
.perm-matrix { width: 100%; border-collapse: collapse; }
.perm-matrix th, .perm-matrix td { text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--surface-border); }
.perm-matrix th:not(:first-child), .perm-matrix td:not(:first-child) { text-align: center; width: 5rem; }
</style>
```

> This view uses PrimeVue v3 components (`DataTable`, `Column`, `Dialog`, `Checkbox`, `InputText`, `Button`, `Tag`) and `useConfirm`/`useToast`. Confirm a `<ConfirmDialog />` and `<Toast />` exist in `AppLayout` (they do for the existing UAM toast usage); if `ConfirmDialog` is not globally mounted, add `<ConfirmDialog />` to the layout. Register any not-yet-global components in `main.js` following the existing PrimeVue registration block.

- [ ] **Step 3: Verify build is clean**

Run: `cd services/client && npm run build`
Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add services/client/src/api/roleAPI.js services/client/src/api/index.js services/client/src/views/admin/RoleManagement.vue
git commit -m "feat(web): role-management page with read/write/execute permission matrix"
```

---

## Task 16: Frontend — rebuild UAM (dynamic roles, manual add, CSV role column)

**Files:**
- Delete: `services/client/src/store/actions/roleActions.js`
- Modify: `services/client/src/views/users/UAM.vue`
- Modify: any `api/*.js` still importing `setAuthHeader`; `store/actions/index.js`

**Interfaces:**
- Consumes: `roleAPI.list` (Task 15), gated user endpoints (Task 9).
- Produces: UAM whose role dropdown is populated from the live roles list, a working "New User" button, and CSV import that requires a `role` column; no `setAuthHeader`/`roleActions`/`getAllRolePermissions` usages.

- [ ] **Step 1: Remove dead role machinery + fix call sites**

```bash
git rm services/client/src/store/actions/roleActions.js
grep -rn "setAuthHeader\|roleActions\|ROLES_PER_MODULE\|getModulesByRole\|getAllRolePermissions" services/client/src
```

Remove every hit: delete `roleActions` from `store/actions/index.js`; in each `api/*.js`, drop the `jwt`/`setAuthHeader` params (cookies now carry auth) — e.g. `getAllDatasets: () => httpClient.get('/datasets/')`. Update the corresponding action callers to stop passing `jwt`. (Note: `roleAPI` from Task 15 is the new roles-domain client and stays.)

- [ ] **Step 2: Populate the role dropdown from the live roles list**

In `UAM.vue` `onMounted`, replace the `getAllRolePermissions` block with a `roleAPI.list()` call:

```js
import { roleAPI } from '@/api'
// ...
onMounted(() => {
  roleAPI.list()
    .then((res) => { roles.value = res.data.map((r) => r.name) })
    .catch(() => { roles.value = [] })
  store.dispatch('getAllUsers')
    .then((res) => { users.value = res.data })
    .catch((err) => {
      const msg = err.response?.data?.message || err.message
      toast.add({ severity: 'error', summary: 'Error', detail: 'Failed to fetch users. ' + msg, life: 5000 })
    })
})
```

Fix the broken default in `onAddUser` (`role: 'readonly'` → no such role): set `role: roles.value?.[0] || null`.

- [ ] **Step 3: Add the working "New User" button**

In the header actions of `UAM.vue` (next to Import/Export), add a primary action gated by `user:write`:

```html
<Button v-can="'user:write'" icon="pi pi-plus" label="New User" @click="onAddUser" />
```

(`onAddUser` already exists but was unreferenced; this wires it to the Add dialog.)

- [ ] **Step 4: Require a role column on CSV import**

The CSV is parsed server-side and dispatched to `addMultiUsers` (`/user/add_batch`), which now rejects rows lacking a valid `role` (Task 9). Surface those row-level errors in `onFileChange`'s catch and add a hint near the Import button:

```js
    .catch((err) => {
      loading.value = false
      const body = err.response?.data
      const detail = body?.errors ? body.errors.join('; ') : (body?.message || err.message)
      toast.add({ severity: 'error', summary: 'Import failed', detail, life: 8000 })
    })
```

Add a tooltip/hint on the Import button: `v-tooltip.bottom="'CSV must include a role column (an existing role name) per row.'"`.

- [ ] **Step 5: Verify build is clean**

Run: `cd services/client && npm run build`
Expected: build succeeds; the grep from Step 1 returns no hits.

- [ ] **Step 6: Commit**

```bash
git add -A services/client/src
git commit -m "feat(web): rebuild UAM with dynamic roles, manual add, and role-column CSV import"
```

---

## Task 17: End-to-end manual verification

**Files:** none (verification only). Requires the local stack (`docker compose -f docker-compose.debug.yml up -d redis mssql minio mlflow`), backend (`flask run --port 5001 --debug`) after `flask db upgrade` + `SEED_ADMIN_PASSWORD=... python manage.py seed_db`, and frontend (`npm run dev`).

- [ ] **Step 1: Login & cookies** — log in as the seeded `sysadmin`; in dev tools confirm `access_token_cookie`/`refresh_token_cookie` are `HttpOnly` and **no JWT exists in `localStorage`/Vuex**.
- [ ] **Step 2: Role management** — open Role Management; create a custom role (e.g. `risk_lead` = `credit_risk:read,credit_risk:execute,dataset:read`); confirm the matrix saved; confirm `sysadmin` is shown as built-in and its edit/delete buttons are disabled.
- [ ] **Step 3: Assign + capability UI** — in UAM create a user with the new `risk_lead` role; log in as them; confirm the menu shows only Credit Risk + Datasets (read) and hides UAM/Role Management/Audit Logs and write actions.
- [ ] **Step 4: Live permission edit** — as sysadmin, add `dataset:write` to `risk_lead`; on the risk_lead session's next request/navigation, confirm the new capability applies **without** forcing a re-login (registry cache invalidation).
- [ ] **Step 5: Server-side enforcement** — as a `viewer`, attempt `POST /api/credit-risk/runs` and `GET /api/roles/` via dev tools → 403; as `sysadmin` → 200.
- [ ] **Step 6: Lockout guards** — try to delete a role that is assigned to a user → 409 with a reassign message; try to `PUT /api/roles/sysadmin` → 403.
- [ ] **Step 7: CSV import** — import a users CSV: one row with a valid `role`, one with an unknown role → confirm the whole import is rejected with a row-level error naming the bad row.
- [ ] **Step 8: Single session / role change** — log in as the same user in a second browser → first browser 401s, silently refresh-fails, redirects to login. As sysadmin, change a logged-in user's assigned role → that user is forced to re-login and the new capability set applies.
- [ ] **Step 9: Refresh & logout** — idle past 15 min (or shorten access expiry) → silent refresh keeps you in; Logout → `/api/auth/me` 401 and cookies cleared.
- [ ] **Step 10: Commit** any small fixes found during verification with focused messages.

---

## Task 18: Documentation & roadmap update

**Files:**
- Modify: `CLAUDE.md`, `.claude/docs/architecture.md`, `.claude/docs/state_management.md`, `.claude/docs/database_models.md`, `PRODUCTION_READINESS.md`

- [ ] **Step 1: Update domain docs**
  - `database_models.md`: remove legacy `roles` + `active_session`; document the new `roles` table (`name`, `permissions` JSON, `is_system`) and `user_sessions`; note `users.role` references a role name (no FK; validated in the API).
  - `architecture.md` + `state_management.md`: replace the JWT-header/refresh description with cookie-based revocable sessions, the catalog + DB-roles + cached-registry model, `require_perm`, the role-management page, and the `/auth/me` bootstrap.
  - `CLAUDE.md` §5: update the RBAC line to the runtime capability model (catalog of `domain:{read,write,execute}`, DB-managed roles, protected `sysadmin`, cookies + single-session).
- [ ] **Step 2: Update `PRODUCTION_READINESS.md`** — mark **S2** resolved by this plan (link `AUTH_RBAC_REBUILD_PLAN.md`); update **S4** (token-in-`localStorage` half done; Encrypt-at-rest still pending); note the `CORS_ORIGIN` guard from **S5** landed in Task 3; in "Suggested sequencing," state this plan runs before the P0 security pass.
- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md .claude/docs PRODUCTION_READINESS.md
git commit -m "docs: document runtime capability RBAC + cookie auth; update roadmap"
```

---

## Self-review notes (for the reviser)

- **Spec coverage:** catalog + resolver (T1); DB roles model/seed/registry (T5); roles CRUD with protection, wildcard rejection, in-use + self-lockout guards (T8); per-request registry resolution so permission edits apply without re-login (T6); login lockout + password policy + revocable cookie sessions + single login (T3/T4/T7); user-management read/write split + DB role validation + strict CSV `role` column (T9); per-endpoint enforcement (T10); legacy removal + migration with seed (T11); frontend cookie/CSRF/refresh (T12), simplified `can()`/`v-can` + `/me` bootstrap (T13), menu/route guards + role-mgmt route (T14), role-management matrix page (T15), UAM rebuild with dynamic roles + manual add + role-column CSV (T16); E2E (T17); docs (T18).
- **Settled design decisions:** (1) protected built-in `sysadmin` (`["*"]`, `is_system`) is the lockout-recovery path; (2) role management is the delegable capability `role:write` / `role:read`; (3) three actions read/write/execute with delete folded into write; (4) CSV bulk import requires a valid `role` column per row (whole batch rejected on any bad row).
- **Resolved open choices:** `/credit-risk/kmv|ecl` compute = `credit_risk:read`; refresh issues a new access token only (no refresh-token rotation); frontend always awaits `/auth/me` on load (no persisted `currentUser`).
- **Known sequencing wrinkles:** the Task 6 decorator tests need login (Task 7) — handle via temporary `xfail`. Deleting `prevent_multiple_logins_per_user` (Task 7 Step 5) is deferred to Task 9 Step 3 so `users/routes.py` keeps importing a live symbol until its decorators are swapped. The new `roles_bp` (`/api/roles`) and the legacy `role` blueprint (`/api/role`) coexist between Task 8 and Task 11; Task 11 removes the legacy one.
- **Cache note:** the role registry uses `flask-caching`; in production this must be the **Redis** backend so invalidation is shared across gunicorn workers. `SimpleCache` (per-process) is for tests/dev only.
