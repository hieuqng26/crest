# Skill: Add a frontend page

A new page = 4 coordinated edits. Missing any one is the usual cause of "route works
but no menu / 404 / blank page".

## Steps
1. **View**: create `src/views/<module>/<Name>.vue` using Composition API
   `<script setup>`. Page-level state with `ref`/`reactive` (not Vuex).
2. **API wrapper**: add/extend `src/api/<domain>API.js` — all calls go through
   `httpClient` from `api/httpClient.js`. NEVER use raw `axios` in a component.
3. **Route**: add an entry in `src/router/index.js` (it carries the auth guard).
4. **Menu**: add an item in `src/layout/AppMenu.vue`, gated by the module/role.

## Conventions
- Imports at top of `<script setup>`, ordered: Vue core → third-party (PrimeVue) →
  local `@/api`, `@/utils`, components. One blank line between groups.
- Dates: use `fmtDate` / `fmtDateShort` from `@/utils/datetime.js` — never call
  `toLocaleDateString`/`toLocaleTimeString` directly.
- Shared helpers live in `src/utils/` — import, don't duplicate inline.
- PrimeVue for behavior (DataTable/Dropdown/Dialog/Menu/OverlayPanel); Tailwind for
  layout/spacing only. Follow `.claude/docs/design.md`.
- Copy structure + styling from `views/calibrate/CalibrateJobs.vue` /
  `CalibrateRun.vue` rather than inventing a new layout.

## v-model caveat
PrimeVue v-model bindings must be a plain ref, not an inline ternary
(`v-model:selection="sel ? a : undefined"` fails to compile). Bind the ref directly
and gate behavior with the relevant prop. See `.claude/bugs/vmodel-ternary-compile-error.md`.
