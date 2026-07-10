"""Monitoring reads: list runs, run detail, and run/workflow logs.

Progress and logs are DB-persisted and polled (there is no push channel).
List tools are paginated (1-based page, per_page ≤ 100); log tools use an
after_id cursor so pollers only fetch new lines.
"""

from typing import Annotated, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from project.mcp_server.runtime import tool_boundary
from project.mcp_server.server import mcp
from project.services import credit_risk as credit_risk_service
from project.services import calibrations as calibration_service
from project.services import forecast_runs as forecast_run_service
from project.services import run_logs as run_log_service
from project.services import workflows as workflow_service

_READ = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

Page = Annotated[int, Field(ge=1, description="1-based page number")]
PerPage = Annotated[int, Field(ge=1, le=100, description="Items per page (max 100)")]


@mcp.tool(name="crest_list_calibration_runs", annotations=_READ)
@tool_boundary
def crest_list_calibration_runs(
    page: Page = 1,
    per_page: PerPage = 20,
    status: str | None = None,
) -> dict:
    """List calibration runs, newest first. Optional status filter: queued |
    running | success | failed. Returns {items, total, page, pages}."""
    return calibration_service.list_runs(page=page, per_page=per_page, status=status)


@mcp.tool(name="crest_get_calibration_run", annotations=_READ)
@tool_boundary
def crest_get_calibration_run(run_id: str) -> dict:
    """One calibration run's status/detail (progress, error_message on failure,
    retraining_segment_count, workflow_run_uuid when workflow-owned)."""
    return calibration_service.get_run(run_id)


@mcp.tool(name="crest_list_forecast_runs", annotations=_READ)
@tool_boundary
def crest_list_forecast_runs(
    page: Page = 1,
    per_page: PerPage = 20,
    status: str | None = None,
) -> dict:
    """List forecast runs, newest first. Optional status filter. Returns
    {items, total, page, pages}."""
    return forecast_run_service.list_runs(page=page, per_page=per_page, status=status)


@mcp.tool(name="crest_get_forecast_run", annotations=_READ)
@tool_boundary
def crest_get_forecast_run(run_id: str) -> dict:
    """One forecast run's status/detail."""
    return forecast_run_service.get_run(run_id)


@mcp.tool(name="crest_list_credit_risk_runs", annotations=_READ)
@tool_boundary
def crest_list_credit_risk_runs(page: Page = 1, per_page: PerPage = 20) -> dict:
    """List credit-risk analysis runs, newest first. Returns {items, total,
    page, pages}; is_active marks the run the Analysis screens read."""
    return credit_risk_service.list_runs(page=page, per_page=per_page)


@mcp.tool(name="crest_get_credit_risk_run", annotations=_READ)
@tool_boundary
def crest_get_credit_risk_run(run_id: str | None = None) -> dict:
    """One credit-risk run's status/detail incl. its result client_ids. Omit
    run_id to get the ACTIVE run (404-style error if none is active)."""
    return credit_risk_service.get_run(run_id)


@mcp.tool(name="crest_list_workflows", annotations=_READ)
@tool_boundary
def crest_list_workflows(page: Page = 1, per_page: PerPage = 20) -> dict:
    """List workflows (train → forecast → credit-analysis pipelines), newest
    first. Returns {items, total, page, pages}."""
    return workflow_service.list_workflows(page=page, per_page=per_page)


@mcp.tool(name="crest_get_workflow", annotations=_READ)
@tool_boundary
def crest_get_workflow(run_id: str, light: bool = True) -> dict:
    """One workflow with per-target calibration/forecast status and the
    analysis run. light=True (default) returns the compact polling payload —
    pass light=False only when you need full per-run details (heavy: includes
    metric blobs)."""
    return workflow_service.get_workflow(run_id, light=light)


@mcp.tool(name="crest_get_run_logs", annotations=_READ)
@tool_boundary
def crest_get_run_logs(
    run_type: Literal["calibration", "forecast", "credit_risk"],
    run_id: str,
    after_id: Annotated[
        int | None,
        Field(description="Cursor: only return log rows with id > after_id"),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=500)] = 200,
) -> dict:
    """A run's log lines, oldest→newest within the page. Without after_id the
    MOST RECENT `limit` lines are returned (log tail); pass the returned
    next_after_id back as after_id to fetch only newer lines when polling a
    live run. Returns {logs, next_after_id, has_more}."""
    return run_log_service.get_logs(run_type, run_id, after_id=after_id, limit=limit)


@mcp.tool(name="crest_get_workflow_logs", annotations=_READ)
@tool_boundary
def crest_get_workflow_logs(
    run_id: str,
    page: Annotated[int, Field(ge=0, description="0-based page number")] = 0,
    page_size: Annotated[int, Field(ge=1, le=200)] = 50,
    step: Annotated[
        Literal["Training", "Forecast", "Credit"] | None,
        Field(description="Only lines from this pipeline step"),
    ] = None,
    level: Annotated[
        Literal["info", "warn", "error"] | None,
        Field(description="Only lines at this level"),
    ] = None,
) -> dict:
    """A workflow's unified training+forecast+credit log lines (newest stage
    first). Returns {rows, total, columns}."""
    filters: dict[str, dict] = {}
    if step:
        filters["step"] = {"mode": "in", "value": [step]}
    if level:
        filters["level"] = {"mode": "in", "value": [level]}
    return workflow_service.get_workflow_logs(
        run_id, page=page, page_size=page_size, filters=filters or None
    )
