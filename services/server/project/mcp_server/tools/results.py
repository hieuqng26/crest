"""Result reads: forecast results, credit-risk results, calibration diagnostics.

Table tools accept the CommonDataTable filter convention as a JSON string:
'{"<column>": {"mode": "contains", "value": "<substr>"}}' or
'{"<column>": {"mode": "in", "value": ["a", "b"]}}'.
"""

from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from project.core import table_query
from project.mcp_server.runtime import tool_boundary
from project.mcp_server.server import mcp
from project.services import calibrations as calibration_service
from project.services import credit_risk as credit_risk_service
from project.services import forecast_runs as forecast_run_service

_READ = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

Page0 = Annotated[int, Field(ge=0, description="0-based page number")]
PageSize = Annotated[int, Field(ge=1, le=200, description="Rows per page (max 200)")]
SortOrder = Annotated[
    str | None, Field(description='"asc" or "desc" (with sort_column)')
]
Filters = Annotated[
    str | None,
    Field(
        description='JSON column filters, e.g. {"sector": {"mode": "in", "value": ["Tech"]}}'
    ),
]


@mcp.tool(name="crest_get_forecast_results", annotations=_READ)
@tool_boundary
def crest_get_forecast_results(
    run_id: str,
    page: Page0 = 0,
    page_size: PageSize = 50,
    sort_column: str | None = None,
    sort_order: SortOrder = None,
    filters: Filters = None,
) -> dict:
    """One page of a forecast run's predicted rows (date, predicted + meta
    columns like sector/segment_key). Returns {rows, total, columns}."""
    return forecast_run_service.get_results(
        run_id,
        page=page,
        page_size=page_size,
        sort_column=sort_column,
        sort_order=sort_order,
        filters=table_query.parse_filters(filters),
    )


@mcp.tool(name="crest_get_credit_risk_results", annotations=_READ)
@tool_boundary
def crest_get_credit_risk_results(
    run_id: str,
    page: Page0 = 0,
    page_size: PageSize = 50,
    sort_column: str | None = None,
    sort_order: SortOrder = None,
    filters: Filters = None,
) -> dict:
    """One page of a credit-risk run's per-client summary (client_id, sector,
    IFRS 9 stage, pd, lgd, lifetime ecl, scenario, year — baseline scenario at
    the latest meaningfully-computed year). Returns {rows, total}. Full
    year×scenario detail: crest_get_credit_risk_client_result."""
    return credit_risk_service.get_run_results(
        run_id,
        page=page,
        page_size=page_size,
        sort_column=sort_column,
        sort_order=sort_order,
        filters=table_query.parse_filters(filters),
    )


@mcp.tool(name="crest_get_credit_risk_client_result", annotations=_READ)
@tool_boundary
def crest_get_credit_risk_client_result(run_id: str, client_id: str) -> dict:
    """One client's full KMV (PD/LGD/Rating per year×scenario) and ECL
    (12-month + lifetime per year×scenario) rows for a credit-risk run.
    client_ids come from crest_get_credit_risk_run."""
    return credit_risk_service.get_client_result(run_id, client_id)


@mcp.tool(name="crest_get_calibration_diagnostics", annotations=_READ)
@tool_boundary
def crest_get_calibration_diagnostics(
    run_id: str, segment_key: str | None = None
) -> dict:
    """Validation metrics for a successful calibration run (or one of its
    segments). Always slim: the multi-MB per-observation arrays (val_obs /
    train_obs) are dropped — aggregate metrics, residuals and fitted arrays
    are kept."""
    return calibration_service.get_diagnostics(run_id, segment_key, slim=True)
