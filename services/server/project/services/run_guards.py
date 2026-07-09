"""Shared pre-conditions for mutating run/workflow rows.

Transport-agnostic — these raise ``DomainError`` subclasses that the API error
boundary maps to HTTP status codes, so the same guards protect the future MCP
tools.
"""

from project.exceptions import ConflictError


def ensure_not_workflow_member(run) -> None:
    """Raise ``ConflictError`` (-> 409) if ``run`` belongs to a workflow.

    Workflow children must be deleted/rerun as part of the whole workflow so
    downstream forecast/analysis results never desync from their training run.
    Replaces the ``_check_workflow_membership`` copy that lived verbatim in the
    calibrations, forecast_runs and credit_risk route modules.
    """
    workflow_run_id = getattr(run, "workflow_run_id", None)
    if not workflow_run_id:
        return
    from project.db_models.workflow_models import WorkflowRun

    wf = WorkflowRun.query.get(workflow_run_id)
    wf_name = wf.name if wf else workflow_run_id
    raise ConflictError(
        f"This run belongs to workflow '{wf_name}' — delete or rerun the "
        "workflow instead."
    )
