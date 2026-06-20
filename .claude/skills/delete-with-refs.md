# Skill: Dependency-checked delete (single + bulk)

Runs are referenced across domains by FK with no cascade, so a naive DELETE raises a
DB 500. The established pattern: pre-check references, block with a clear 409 +
dependency list, and keep the console clean.

## Backend
1. Add `GET /<run_id>/refs` returning the dependents, e.g.
   `{"forecast_runs": [{"run_id","name","status"}, ...]}`.
2. In `DELETE /<run_id>`: query dependents first; if any, return
   `jsonify({"error": "...", "<dep>": [...]}), 409`. Otherwise delete and return 204.
3. Add `POST /bulk-delete` taking `{"run_ids":[...]}`; skip blocked ones and return
   `{"deleted": n, "deleted_ids": [...], "skipped": m}` (the explicit `deleted_ids`
   lets the UI update accurately).

Reference helpers: `_check_forecast_references()` in `api/calibrations/routes.py`,
`_cr_refs_for()` in `api/forecast_runs/routes.py`. Known FK blocks are listed in
`.claude/docs/database_models.md`.

## Frontend
1. API wrapper: `refs(runId)`, `delete(runId)`, `bulkDelete(runIds)`. Use
   `validateStatus: (s) => s < 500` on delete so an expected 409 does NOT log a
   console error.
2. Delete dialog: on open, fetch `refs`; if dependents exist, list them (with links)
   and disable the Confirm button.
3. Bulk delete: call `exitSelectMode()` first (immediate UI feedback), then the API,
   then **re-fetch the list** from the server — do not optimistically filter rows by
   status (caused "0 deleted, 3 skipped" yet rows vanished). The endpoint returns
   explicit `deleted_ids`; trust the server response, not a client-side guess.

Reference implementation: `views/calibrate/CalibrateJobs.vue` (single + bulk),
mirrored in `ForecastJobs.vue` and `CreditRiskJobs.vue`.
