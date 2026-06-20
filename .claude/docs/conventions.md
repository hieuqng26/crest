# Coding Conventions

## Python / Backend (enforced by `ruff`)
- All imports at the top of the file — never inside functions/conditionals, unless a
  deferred import is strictly required to break a circular import or missing app
  context (comment why).
- Import order: stdlib → third-party → local (`project.*`), one blank line between groups.
- Line length 88. Double quotes throughout.
- API modules: `api/<domain>/__init__.py` + `routes.py` (+ models in `db_models/`).
  Register the blueprint in `project/__init__.py`.
- Business logic in `project/core/`, not in route handlers.
- Validate all incoming JSON with Pydantic before any DB write or task dispatch.
- DB writes via the `app_session()` context manager.
- Log with `get_logger(__name__)` — never `print()`.
- Errors: `return jsonify({"error": "message"}), <status>`. No stack traces to client.
- **After any Python edit run, from `services/server/`:**
  `ruff check . --exclude migrations --fix && ruff format . --exclude migrations`
  — all checks must pass before the work is done.

## Vue / Frontend
- Composition API with `<script setup>` everywhere. No Options API.
- Imports at top of `<script setup>`, ordered Vue core → third-party → local
  (`@/api`, `@/utils`, components); one blank line between groups.
- All HTTP through `src/api/` wrappers (which use `httpClient`) — never raw axios.
- Vuex for global auth/role/user/log state only; page state is component-local.
- Dates via `fmtDate`/`fmtDateShort` from `@/utils/datetime.js` — never
  `toLocaleDateString`/`toLocaleTimeString` in a component.
- Shared helpers in `src/utils/` — import, don't duplicate.
- PrimeVue for behavior, Tailwind for layout/spacing; styling per `.claude/docs/design.md`.

## General
- Comments explain WHY (non-obvious constraints/workarounds), never WHAT.
- No unused imports, dead code, or backwards-compat shims.
- New feature → mirror the shape of the closest existing analogous feature.
- Git commits: never include `Co-Authored-By` trailers.
