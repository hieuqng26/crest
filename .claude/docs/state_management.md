# State Management & Auth

Frontend global state, the cookie/session auth lifecycle, RBAC, and the progress-polling pattern.

## Vuex store (`src/store/`)

- `store/index.js` holds global state: `currentUser`, `permissions` (array of strings),
  and domain-scoped state for running jobs.
- `currentUser` and `permissions` are **NOT** persisted across reloads (no
  `vuex-persistedstate` for auth) — they are re-populated by `/auth/me` on every page
  load. This means no stale tokens in `localStorage` survive a server-side revocation.
- Domain actions live in `store/actions/`. Page-level state stays in components
  (`ref`/`reactive`), NOT Vuex.
- Key mutations/actions:
  - `setAuth({ user, permissions })` — populates `currentUser` + `permissions` after login
    or `/auth/me` bootstrap.
  - `clearAuth()` — wipes `currentUser` + `permissions` on logout or forced session
    expiry.
  - `login(credentials)` — POST `/api/auth/login`, then calls `setAuth`.
  - `fetchMe()` — GET `/api/auth/me`, calls `setAuth`; called at app boot and after
    silent refresh.
  - `logout()` — POST `/api/auth/logout`, then `clearAuth`.
- Key getters:
  - `isAuthenticated` → `!!currentUser`.
  - `getCurrentUser` → `currentUser` object.
  - `can(permission)` — delegates to `utils/permissions.js` `can(permissions, permission)`;
    returns `true` if the user has the exact permission or the wildcard `"*"`.

## Cookie auth lifecycle (`src/api/httpClient.js`)

Auth tokens are carried exclusively in **httpOnly cookies** set by the server at login —
they are never accessible to JavaScript. The frontend does not store or inject tokens.

- `withCredentials: true` on every axios request so cookies are included cross-origin.
- **CSRF:** the server sets a readable `csrf_access_token` cookie (not httpOnly). The
  request interceptor reads it via `utils/cookies.js` `getCookie()` and injects it as an
  `X-CSRF-TOKEN` header. The refresh request uses `csrf_refresh_token` instead.
  `WTF_CSRF_ENABLED=False` on the backend is intentional — CSRF protection is handled by
  this custom header mechanism (Flask-JWT-Extended validates it).
- **Response interceptor (401 handling):**
  - `"new login"` body → `clearAuth` + redirect to `/auth/login` (server kicked this
    session because another login occurred).
  - Generic 401 → single-flight silent refresh: the first 401 calls `POST /api/auth/refresh`
    (with `csrf_refresh_token`), queues concurrent requests in `refreshSubscribers`, then
    retries them all. A 401 on `/auth/refresh` itself fails hard → `clearAuth` + redirect.

## App bootstrap (`main.js`)

Before mounting the Vue app, `store.dispatch('fetchMe')` is awaited:
- If `/auth/me` returns 200: `setAuth` populates `currentUser` + `permissions`. App mounts normally.
- If it returns 401 (no valid session): `clearAuth`; the router guard redirects to `/auth/login`.

This guarantees the store always reflects the *server-side* session state, not a cached
frontend snapshot.

## RBAC (`src/utils/permissions.js`, `src/directives/can.js`)

The permission model is a catalog of **`domain:{read,write,execute}`** strings (9 domains,
3 actions each). The `sysadmin` role carries the wildcard `"*"`.

- `can(permissions, permission)` — pure function; `true` if `permissions` includes the
  exact string or `"*"`. Exported from `utils/permissions.js`.
- `v-can="'domain:action'"` — Vue directive registered globally in `main.js`. Removes
  the element from the DOM if the current user lacks the permission. Backed by the Vuex
  `can(perm)` getter.
- `AppMenu.vue` — each menu item has a `permission` field; items are filtered client-side
  using `v-can`. A "Role Management" item is gated by `role:read`.
- **Router guard (`router/index.js`):** `beforeEach` awaits `fetchMe` if `currentUser` is
  absent, then checks `route.meta.requiresPerm` against the Vuex `can` getter. Redirects
  to `/auth/login` if unauthenticated; to `/unauthorized` if authenticated but lacking
  the required permission.

### Built-in roles (seeded by `api/roles/defaults.py`)

| Role | Permissions | Notes |
|---|---|---|
| `sysadmin` | `["*"]` | `is_system=True`; cannot be deleted or renamed; lockout-recovery path |
| `analyst` | data + calibration + forecast + credit-risk read/write/execute | default power user |
| `viewer` | read on all domains | read-only across all runs and diagnostics |

Roles are DB-managed (editable via the Role Management page, `/admin/role-management`,
gated by `role:write`). The permission catalog is served at `GET /api/roles/catalog`.

### Role Management page (`views/admin/RoleManagement.vue`)

Full CRUD interface: create/edit/delete roles, permission matrix (domain × read/write/execute
checkboxes). Uses `api/roleAPI.js` (`list`, `catalog`, `create`, `update`, `remove`).
Built-in (`is_system`) roles cannot be deleted; wildcard assignment is blocked via the API.

## Progress / log polling (no SocketIO)

Long-running jobs (calibration, forecast, credit-risk) do **not** push over a socket.
The Celery task writes progress + log lines to `*_run_logs` DB tables; the run-view
pages poll the run endpoint (and `/logs`) on an interval while `status` is
`queued`/`running`, and stop once terminal. When adding a new long job, follow the
same poll-until-terminal pattern — never add a websocket.
