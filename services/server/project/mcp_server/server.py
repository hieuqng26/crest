"""The CREST FastMCP server instance and tool registration.

Importing this module registers every ``crest_*`` tool on ``mcp``. It does NOT
create the Flask app — that happens lazily on the first tool call (or eagerly
in ``__main__``), so tests can inspect the tool registry without a database.
"""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "crest_mcp",
    instructions=(
        "CREST banking ML calibration platform. Typical pipeline: discover "
        "inputs (crest_list_datasets / crest_list_model_configs / "
        "crest_get_model_registry) → launch a run or a full workflow "
        "(crest_create_* / crest_create_workflow) → poll status "
        "(crest_get_*_run / crest_get_workflow / crest_get_run_logs) → read "
        "results (crest_get_forecast_results / crest_get_credit_risk_results / "
        "crest_get_analysis_*). Launches are asynchronous: they return a "
        "QUEUED run and Celery workers do the compute — poll until status is "
        "'success' or 'failed'. run_id values are immutable UUIDs; a rerun "
        "creates new runs."
    ),
)

# Importing the tool modules registers their @mcp.tool functions.
from project.mcp_server.tools import (  # noqa: E402,F401
    analysis,
    launch,
    refs,
    results,
    runs,
)
