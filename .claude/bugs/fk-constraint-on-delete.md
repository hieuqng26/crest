# Bug: FK constraint 500 when deleting a run

**Symptom:** Deleting a calibration job returns 500
(`FK__forecast___calib__...` / IntegrityError). Same when deleting a forecast run
referenced by a credit-risk run.

**Cause:** Cross-domain FKs have no cascade:
- `forecast_runs.calibration_run_id` → calibration_runs
- `credit_risk_run_forecast_inputs.forecast_run_id` → forecast_runs
A raw DELETE on the parent lets the DB raise.

**Fix:** Pre-check dependents and block with a clear **409 + dependency list** instead
of deleting. Implemented via `GET /<run_id>/refs` + guarded `DELETE` + `POST
/bulk-delete`. Full procedure in `.claude/skills/delete-with-refs.md`.

**Prevention:** Before deleting any run, consult the dependency chain in
`.claude/docs/database_models.md`. Never cascade-delete cross-domain without the user
explicitly asking — the user rejected automatic cascade; blocking with a message is
the agreed behavior.
