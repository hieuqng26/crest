"""Credit-risk analysis reads: meta, sector heatmap, financial forecast.

These read a run's MATERIALISED level series. If the series hasn't been
computed yet the tool returns {"status": "materializing", ...} and dispatches
the backfill — retry after a short wait (requires a running Celery worker).
"""

from typing import Annotated, Literal

from mcp.types import ToolAnnotations
from pydantic import Field

from project.mcp_server.runtime import tool_boundary
from project.mcp_server.server import mcp
from project.services import credit_risk_analysis as analysis_service

_READ = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    # Not idempotent in the strictest sense: an unmaterialised run triggers a
    # one-off backfill dispatch. Reads are otherwise repeat-safe.
    idempotentHint=True,
    openWorldHint=False,
)

RunId = Annotated[
    str | None,
    Field(description="Credit-risk run UUID; omit to use the active run"),
]


@mcp.tool(name="crest_get_analysis_meta", annotations=_READ)
@tool_boundary
def crest_get_analysis_meta(run_id: RunId = None) -> dict:
    """Sectors, companies-by-sector, available metrics and forecast targets
    for a credit-risk run's Analysis screens — call this first to learn the
    valid arguments for the heatmap/forecast tools."""
    try:
        return analysis_service.get_analysis_meta(run_id)
    except analysis_service.AnalysisSeriesPending as exc:
        return analysis_service.series_pending_payload(exc.run)


@mcp.tool(name="crest_get_analysis_heatmap", annotations=_READ)
@tool_boundary
def crest_get_analysis_heatmap(
    metric: Literal["revenue_growth", "cogs_margin", "leverage"] = "revenue_growth",
    run_id: RunId = None,
    sector: Annotated[
        str | None,
        Field(
            description="Drill into one sector's clients; omit for the sector overview"
        ),
    ] = None,
    clients: Annotated[
        list[str] | None,
        Field(description="With sector: restrict the drill-down to these client_ids"),
    ] = None,
    scenario: str | None = None,
) -> dict:
    """Year×(sector|client) heatmap of a financial metric across the forecast
    horizon (History + scenario years)."""
    try:
        return analysis_service.get_analysis_heatmap(
            metric,
            run_id=run_id,
            sector=sector,
            clients=set(clients) if clients else None,
            scenario=scenario,
        )
    except analysis_service.AnalysisSeriesPending as exc:
        return analysis_service.series_pending_payload(exc.run)


@mcp.tool(name="crest_get_analysis_forecast", annotations=_READ)
@tool_boundary
def crest_get_analysis_forecast(
    sector: str,
    run_id: RunId = None,
    client_id: Annotated[
        str | None,
        Field(description="One company instead of the whole sector"),
    ] = None,
    targets: Annotated[
        list[str] | None,
        Field(
            description="Forecast target keys to include (see crest_get_analysis_meta)"
        ),
    ] = None,
    indexed: Annotated[
        bool,
        Field(
            description="Rebase every series to base year = 100 for shape comparison"
        ),
    ] = False,
) -> dict:
    """Historical + multi-scenario forecast level series for a sector (or one
    of its clients) across the linked forecast targets."""
    try:
        return analysis_service.get_analysis_forecast(
            sector,
            run_id=run_id,
            client_id=client_id,
            requested_keys=set(targets) if targets else None,
            indexed=indexed,
        )
    except analysis_service.AnalysisSeriesPending as exc:
        return analysis_service.series_pending_payload(exc.run)
