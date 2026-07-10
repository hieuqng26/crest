"""Launch tools — create/rerun runs via the same services the HTTP API uses.

All launches are ASYNCHRONOUS: the tool returns immediately with a QUEUED run
dict. Redis and a Celery worker must be running for the run to progress —
otherwise it stays "queued" forever. Poll with the crest_get_* tools and
crest_get_run_logs; never spin-wait in a tight loop (runs take minutes).
"""

from mcp.types import ToolAnnotations

from project.constants import LaunchOrigin
from project.mcp_server.runtime import MCP_IDENTITY, tool_boundary
from project.mcp_server.server import mcp
from project.schemas.calibrations import CreateCalibrationRun
from project.schemas.credit_risk import CreateCreditRiskRun
from project.schemas.forecast_runs import CreateForecastRun
from project.schemas.workflows import CreateWorkflow
from project.services import calibrations as calibration_service
from project.services import credit_risk as credit_risk_service
from project.services import forecast_runs as forecast_run_service
from project.services import workflows as workflow_service

_LAUNCH = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)


@mcp.tool(name="crest_create_calibration_run", annotations=_LAUNCH)
@tool_boundary
def crest_create_calibration_run(params: CreateCalibrationRun) -> dict:
    """Launch a calibration (model-training) run for a dataset + model config.

    Find dataset_id via crest_list_datasets (kind "calibration") and
    model_config_id via crest_list_model_configs. Async: returns the QUEUED
    run (with its immutable run_id) — poll crest_get_calibration_run until
    status is "success"/"failed", then read crest_get_calibration_diagnostics.
    """
    return calibration_service.create_run(params, MCP_IDENTITY, LaunchOrigin.AUTO)


@mcp.tool(name="crest_create_forecast_run", annotations=_LAUNCH)
@tool_boundary
def crest_create_forecast_run(params: CreateForecastRun) -> dict:
    """Launch a forecast for a SUCCESSFUL calibration run against a forecast
    dataset (kind "forecast").

    Async: returns the QUEUED run — poll crest_get_forecast_run, then read
    crest_get_forecast_results.
    """
    return forecast_run_service.create_run(params, MCP_IDENTITY, LaunchOrigin.AUTO)


@mcp.tool(name="crest_create_credit_risk_run", annotations=_LAUNCH)
@tool_boundary
def crest_create_credit_risk_run(params: CreateCreditRiskRun) -> dict:
    """Launch an IFRS 9 credit-risk (KMV PD/LGD + ECL) analysis run.

    cal_inputs maps slot name → successful forecast run UUID; the slots
    total_assets, short_term_debts and long_term_debts are required (KMV needs
    them), total_revenue / total_cogs additionally unlock the analysis
    heatmap/forecast screens. dataset_id is a credit dataset (kind "credit").
    Async: poll crest_get_credit_risk_run, then read
    crest_get_credit_risk_results.
    """
    return credit_risk_service.create_run(params, MCP_IDENTITY, LaunchOrigin.AUTO)


@mcp.tool(name="crest_create_workflow", annotations=_LAUNCH)
@tool_boundary
def crest_create_workflow(params: CreateWorkflow) -> dict:
    """Launch a full multi-target workflow: train one calibration per target →
    forecast each → run the credit-risk analysis. Datasets are resolved
    automatically to the latest ready upload of each kind (preview them with
    crest_resolve_workflow_datasets).

    Async: returns the QUEUED workflow plus its created calibration runs —
    poll crest_get_workflow (light) until it finishes; stages advance
    automatically.
    """
    return workflow_service.create_workflow(params, MCP_IDENTITY, LaunchOrigin.AUTO)


@mcp.tool(name="crest_rerun_workflow", annotations=_LAUNCH)
@tool_boundary
def crest_rerun_workflow(run_id: str) -> dict:
    """Relaunch an existing workflow from its stored targets/analysis params
    against the current latest datasets. Creates NEW runs (run_ids are
    immutable — nothing is mutated in place). Async, like crest_create_workflow.
    """
    return workflow_service.rerun_workflow(run_id, MCP_IDENTITY, LaunchOrigin.AUTO)
