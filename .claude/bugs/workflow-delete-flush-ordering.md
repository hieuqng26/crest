# Bug: FK violation deleting a workflow (flush ordering)

**Symptom:** `DELETE /api/workflows/<run_id>` returns 500 with
`IntegrityError ... fk_calibration_runs_workflow_run_id ... DELETE FROM workflow_runs`.
The parent `workflow_runs` row is deleted before its child `calibration_runs`
(also `forecast_runs`, `credit_risk_forecast_inputs`).

**Cause:** `WorkflowRun` has **no ORM `relationship()`** to its child runs — the
`workflow_run_id` FKs are bare `Column`/`ForeignKey` definitions
(`calibration_models.py`, `forecast_models.py`, `credit_models.py`). SQLAlchemy's
unit-of-work orders DELETEs at flush time using relationship dependency edges; with
none present it has no constraint and can emit the parent DELETE before the children.
All `s.delete(...)` calls in `delete_workflow` were pending in one flush at
`commit()`, so ordering was undefined. SQLite (tests) tolerated it; MSSQL enforces the
FK and raised. Same latent hazard for `forecast_runs -> calibration_runs` and
`credit_risk_forecast_inputs -> forecast_runs`.

**Fix:** In `api/workflows/routes.py::delete_workflow`, `s.flush()` after each
dependency level (credit-risk runs → forecast runs → calibration runs → workflow) so
children are physically removed before the rows they reference, regardless of UOW sort.

**Update (async + set-based rewrite):** the per-row `s.delete(...)` cascade path was
also **slow** — SQLAlchemy SELECTed and DELETEd every child result/log row one at a
time (tens of thousands of round-trips). The delete is now:
- **Async:** the route validates (same 409 pre-checks), flips `WorkflowRun.status` to
  `"deleting"`, returns **202**, and dispatches the `delete_workflow` Celery task. The
  frontend shows a "Deleting…" row and polls until it disappears (AWS-instance style).
- **Set-based:** the purge logic lives in `project/core/workflow_delete.py::purge_workflow`,
  which issues one `DELETE ... WHERE col IN (...)` per table, child-first in FK order
  (each `.delete()` executes immediately, so ordered statements stay FK-valid — no
  flush juggling needed). It also removes MinIO artifacts under `artifacts/{run_id}/`
  via `storage.remove_prefix` (best-effort).
The flush-ordering insight below still holds and is the reason the bulk deletes must be
issued child-first.

**Prevention:** When deleting rows linked only by bare FK columns (no `relationship()`),
never rely on the unit-of-work to order multi-table DELETEs — issue explicit set-based
deletes child-first (or flush between levels), or add a relationship with proper cascade.
Prefer set-based deletes over ORM cascade for large child tables. Don't trust the SQLite
test suite to catch FK ordering; MSSQL is stricter. Related:
[fk-constraint-on-delete.md](fk-constraint-on-delete.md).
