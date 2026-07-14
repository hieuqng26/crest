"""Reusable audit-logging decorator for state-changing routes.

`log_audit` (models.py) is the low-level writer; it is called inline in the auth /
users / roles blueprints. For the action-heavy modules (datasets, model configs,
calibrations, forecast runs, credit risk, workflows) we instead wrap the write/execute
handlers with :func:`audit_action` so every launch / delete / cancel / rerun / activate
lands in the ``audit_logs`` table with a single decorator line.

Apply it INSIDE ``@require_perm`` (i.e. on the line just above ``def``) so unauthorized
requests are rejected by ``require_perm`` — which logs its own ``AccessDenied`` — and
never reach the handler or this decorator.
"""

from functools import wraps

from flask import make_response

from project import db
from project.api.auditlog.models import log_audit

# URL kwargs that carry a run/job identifier, and response-body keys that carry a
# freshly created one — used to populate AuditLog.job_id (shown in the AuditLog.vue
# row expansion) so an audited action links back to its run.
_ID_KWARGS = ("run_id", "cr_run_id", "job_id", "dataset_id", "config_id", "segment_key")
_ID_BODY_KEYS = ("run_id", "cr_run_id", "id", "job_id")


def _resource_id(kwargs: dict, body) -> str:
    """Best-effort resource identifier from URL kwargs first, then the response body."""
    for key in _ID_KWARGS:
        val = kwargs.get(key)
        if val not in (None, ""):
            return str(val)
    if isinstance(body, dict):
        for key in _ID_BODY_KEYS:
            val = body.get(key)
            if val not in (None, ""):
                return str(val)
    return ""


def _job_id(kwargs: dict, body) -> str:
    """Run identifier for AuditLog.job_id — dataset/config ids are not jobs, so skip them."""
    for key in ("run_id", "cr_run_id", "job_id"):
        val = kwargs.get(key)
        if val not in (None, ""):
            return str(val)
    if isinstance(body, dict):
        for key in ("run_id", "cr_run_id", "job_id"):
            val = body.get(key)
            if val not in (None, ""):
                return str(val)
    return ""


def _describe(describe, action, submodule, kwargs, body) -> str:
    """Resolve the human-readable description (custom callable or a generic default)."""
    if describe is not None:
        return describe(kwargs, body)
    rid = _resource_id(kwargs, body)
    subject = f"{submodule} {rid}".strip() if rid else submodule
    return f"User [$USER] performed {action} on {subject}".strip()


def audit_action(action, module, submodule, *, describe=None, database_involved=""):
    """Log a state-changing route to the audit trail on both success and failure.

    Args:
        action: short verb stored in ``AuditLog.action`` (e.g. "Launch", "Delete").
        module / submodule: taxonomy stored on the row (free text, matching the
            existing convention such as ``uam``/``user``, ``rbac``/``role``).
        describe: optional ``callable(kwargs, body) -> str`` for the description;
            ``$USER`` is expanded by ``log_audit``. Falls back to a generic message.
        database_involved: comma-separated table names for the row's audit context.
    """

    def wrapper(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            try:
                # Normalize tuple / Response returns to one object with a status code.
                # Runs after any ``with app_session():`` block in the handler has
                # already committed, so log_audit's own commit never persists partial
                # state.
                resp = make_response(fn(*args, **kwargs))
            except Exception:  # handler raised (e.g. a DomainError)
                # Clear the failed transaction before log_audit commits its own row.
                db.session.rollback()
                log_audit(
                    action=action,
                    module=module,
                    submodule=submodule,
                    description=_describe(describe, action, submodule, kwargs, None),
                    error_codes="500",
                    database_involved=database_involved,
                    job_id=_job_id(kwargs, None),
                )
                raise  # let the global error boundary map it to a response

            body = resp.get_json(silent=True) if resp.is_json else None
            status = resp.status_code
            log_audit(
                action=action,
                module=module,
                submodule=submodule,
                description=_describe(describe, action, submodule, kwargs, body),
                error_codes="" if status < 400 else str(status),
                database_involved=database_involved,
                job_id=_job_id(kwargs, body),
            )
            return resp

        return inner

    return wrapper
