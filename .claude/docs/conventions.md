# Coding Conventions

## Python / Backend (enforced by `ruff`)
- All imports at the top of the file — never inside functions/conditionals, unless a
  deferred import is strictly required to break a circular import (comment why, e.g.
  the mutually-recursive Celery tasks in `workers/*`) or to avoid app-context issues.
- Import order: stdlib → third-party → local (`project.*`), one blank line between groups.
- Line length 88. Double quotes throughout.
- **Layering** (detail + "add an endpoint/tool" recipe in [backend.md](backend.md)):
  route = `@bp.verb` + `@require_perm` + parse a Pydantic schema (`project/schemas/`)
  + call a service (`project/services/`) + `jsonify`. Services are
  **transport-agnostic** (no `flask` import) so the MCP server reuses them; pure
  computation lives in `project/core/`.
- Validate incoming JSON with a Pydantic schema in `project/schemas/` (the route
  calls `Schema.model_validate(...)`, `extra="forbid"` + `max_length`); DB-dependent
  checks live in the service. **Do not** add regex input "WAF" filtering — SQLi is
  prevented by the ORM (parameterized), not by scrubbing input; see "Request
  guarding" in [backend.md](backend.md).
- Errors: raise a `DomainError` subclass (`project/exceptions.py`) — the global
  boundary (`project/api/error_handlers.py`) maps it to a status + JSON. Never build
  error tuples in a service, never wrap a whole route in `try/except`, never leak a
  stack trace or exception message to the client.
- DB writes via `app_session()`; **in Celery tasks**, progress/log writes go through
  `worker_session()` (independent session — see the detached-instance bug doc).
- Serialisation: plain column dumps inherit `SerializerMixin.to_dict`; custom shapes
  override it (may call `self.column_dict()`).
- Log with `get_logger(__name__)` — never `print()`.
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
