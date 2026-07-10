"""Shared enums and sentinels for run lifecycle state.

These replace scattered string/int literals for run status, workflow stage,
dataset kind, and job progress. All enums subclass ``str``/``int`` so their
members compare equal to and serialise identically to the raw literals they
replace — persisting ``RunStatus.SUCCESS`` writes ``"success"`` to the DB and
emits ``"success"`` in JSON, so adopting them is behaviour-preserving.
"""

from enum import Enum, IntEnum


class RunStatus(str, Enum):
    """Lifecycle status shared by calibration, forecast, credit-risk and
    workflow runs (the ``status`` column on each ``*_runs`` table)."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    DELETING = "deleting"


class WorkflowStage(str, Enum):
    """``WorkflowRun.current_stage`` — the train -> forecast -> analysis pipeline."""

    TRAINING = "training"
    FORECAST = "forecast"
    ANALYSIS = "analysis"
    DONE = "done"


class DatasetKind(str, Enum):
    """``Dataset.kind`` — what pipeline stage a dataset feeds."""

    CALIBRATION = "calibration"
    FORECAST = "forecast"
    CREDIT = "credit"
    FINANCIAL_PORTFOLIO = "financial_portfolio"


class LaunchOrigin(str, Enum):
    """How a run/workflow was launched — the ``origin`` column on each
    ``*_runs`` / ``workflow_runs`` table, surfaced as the AUTO/MANUAL tag in
    job history.

    ``MANUAL`` = a human via the New Model wizard (the HTTP API). ``AUTO`` = the
    MCP server (New Model "Auto" mode / agent-driven). The launching transport
    sets it: HTTP routes default to MANUAL, MCP tools pass AUTO.
    """

    MANUAL = "manual"
    AUTO = "auto"


class Progress(IntEnum):
    """Well-known job-progress sentinels written to the ``progress`` column.

    Intermediate step percentages remain inline literals at their call sites
    (they are per-task step markers, not a shared vocabulary); only the
    universal sentinels are named here — ``FAILED = -1`` in particular is the
    signal the frontend polls for to stop and surface the error.
    """

    FAILED = -1
    START = 0
    COMPLETE = 100
