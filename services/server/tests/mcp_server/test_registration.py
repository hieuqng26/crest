"""The tool registry itself: names, annotations, and schema caps.

No DB needed — importing the server registers the tools.
"""

import asyncio

from project.mcp_server.server import mcp

EXPECTED_TOOLS = {
    # launch
    "crest_create_calibration_run",
    "crest_create_forecast_run",
    "crest_create_credit_risk_run",
    "crest_create_workflow",
    "crest_rerun_workflow",
    # monitor
    "crest_list_calibration_runs",
    "crest_get_calibration_run",
    "crest_list_forecast_runs",
    "crest_get_forecast_run",
    "crest_list_credit_risk_runs",
    "crest_get_credit_risk_run",
    "crest_list_workflows",
    "crest_get_workflow",
    "crest_get_run_logs",
    "crest_get_workflow_logs",
    # results
    "crest_get_forecast_results",
    "crest_get_credit_risk_results",
    "crest_get_credit_risk_client_result",
    "crest_get_calibration_diagnostics",
    # refs
    "crest_list_datasets",
    "crest_list_model_configs",
    "crest_get_model_registry",
    "crest_list_pd_ratings",
    "crest_resolve_workflow_datasets",
    # analysis
    "crest_get_analysis_meta",
    "crest_get_analysis_heatmap",
    "crest_get_analysis_forecast",
}

LAUNCH_TOOLS = {t for t in EXPECTED_TOOLS if "create" in t or "rerun" in t}


def _tools():
    return asyncio.run(mcp.list_tools())


def test_all_tools_registered():
    names = {t.name for t in _tools()}
    assert names == EXPECTED_TOOLS


def test_every_tool_is_annotated_and_prefixed():
    for t in _tools():
        assert t.name.startswith("crest_")
        assert t.annotations is not None, t.name
        assert t.annotations.destructiveHint is False, t.name
        assert t.annotations.openWorldHint is False, t.name
        assert t.description, t.name


def test_read_only_hints_match_tool_kind():
    for t in _tools():
        expected_ro = t.name not in LAUNCH_TOOLS
        assert t.annotations.readOnlyHint is expected_ro, t.name


def test_pagination_caps_in_schema():
    schemas = {t.name: t.inputSchema for t in _tools()}
    per_page = schemas["crest_list_calibration_runs"]["properties"]["per_page"]
    assert per_page["maximum"] == 100
    limit = schemas["crest_get_run_logs"]["properties"]["limit"]
    assert limit["maximum"] == 500
    page_size = schemas["crest_get_forecast_results"]["properties"]["page_size"]
    assert page_size["maximum"] == 200
