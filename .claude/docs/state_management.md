# State Management & Auth

Frontend global state, the JWT lifecycle, RBAC, and the progress-polling pattern.

## Vuex store (`src/store/`)

- `store/index.js` holds global state: `currentUser`, `jwt`, `roles`, `ROLES_PER_MODULE`.
- Persisted across reloads with **vuex-persistedstate** — the user stays logged in.
- Domain actions live in `store/actions/` (`authActions`, `userActions`, `roleActions`,
  `logActions`). Page-level state stays in components (`ref`/`reactive`), NOT Vuex.
- Key getters:
  - `isAuthenticated` → `accessToken && isValidJwt(accessToken)`.
  - `getCurrentUser` → parsed `currentUser`.
  - `getModulesByRole(roleType)(role)` → list of modules the role can read/write/execute.

## JWT lifecycle (`src/api/httpClient.js`)

- Access token: 10 min. Refresh token: 720 min. Both validated client-side by
  `isValidJwt()` (`src/utils`).
- **Request interceptor** injects `Authorization: Bearer <accessToken>` from
  `store.state.jwt.accessToken`, unless the caller already set the header (e.g. the
  refresh request).
- **Response interceptor** handles 401s:
  - Invalid username/password → reject with annotated error (shown on login).
  - "new login" message → clear session, `logout`, redirect to `/auth/login`.
  - Generic 401 → single-flight token refresh: the first 401 calls
    `store.dispatch('refreshToken')` (swapping `xsrfCookieName` to
    `csrf_refresh_token`), queues concurrent requests in `refreshSubscribers`, then
    retries them all with the new token. A 401 on `/auth/refresh` itself fails hard.
- `withCredentials: true` + `xsrfCookieName` — JWT cookies carry CSRF tokens.
  `WTF_CSRF_ENABLED=False` on the backend is intentional for this JWT-only API.

## RBAC

- Roles: `sysadmin`, `analyst`, `viewer`. Checked per-route on the backend via the
  `roles` table; mirrored to the frontend in `ROLES_PER_MODULE` to gate menu items.
  - `analyst`: upload data, create configs, trigger calibration/forecast/credit-risk.
  - `viewer`: read-only across all runs and diagnostics.
- Menu visibility in `AppMenu.vue` keys off the user's role + module permissions.

## Progress / log polling (no SocketIO)

Long-running jobs (calibration, forecast, credit-risk) do **not** push over a socket.
The Celery task writes progress + log lines to `*_run_logs` DB tables; the run-view
pages poll the run endpoint (and `/logs`) on an interval while `status` is
`queued`/`running`, and stop once terminal. When adding a new long job, follow the
same poll-until-terminal pattern — never add a websocket.
