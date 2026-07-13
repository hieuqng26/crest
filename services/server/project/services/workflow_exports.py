"""Workflow output exports (transport-agnostic).

Backs the Download tab. A workflow produces three tabular outputs — combined
model backtest predictions, combined forecast results, and full per-client
credit detail. Each can be exported to csv/xlsx, but a full-dataset build can be
hundreds of thousands of rows, so generation is async: a route creates an
``ExportJob`` (status ``queued``) and dispatches ``export_dataset`` on the
dedicated ``exports`` Celery queue; the worker calls :func:`build_export_bytes`,
uploads the file to MinIO, and flips the job to ``success``.

No Flask here — routes pass plain args and receive dicts, and the worker reuses
the same builders. The DataFrame builders live in the calibration/workflow
services (reused, not duplicated).
"""

import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd

from project import app_session
from project.core import storage, tabular_export
from project.db_models.calibration_models import (
    CalibrationRun,
    CalibrationRunSegment,
)
from project.db_models.credit_models import CreditRiskResult, CreditRiskRun
from project.db_models.export_models import ExportJob
from project.db_models.forecast_models import ForecastRun
from project.db_models.workflow_models import WorkflowRun
from project.exceptions import BadRequestError, NotFoundError
from project.services import calibrations as calibration_service
from project.services import workflows as workflow_service

# How long a generated file (and its job row) is kept before the beat sweep
# reclaims it. Regenerating is cheap, so a short window bounds MinIO growth.
EXPORT_RETENTION_HOURS = int(os.getenv("EXPORT_RETENTION_HOURS", "24"))

ACTIVE_STATUSES = ("queued", "running")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _naive(dt: datetime | None) -> datetime | None:
    """Drop tzinfo so aware (freshly built) and naive (DB read-back) timestamps
    compare cleanly — the DateTime columns store naive UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _get_workflow(run_id: str) -> WorkflowRun:
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        raise NotFoundError("Workflow not found")
    return wf


def _analysis_run(wf: WorkflowRun) -> CreditRiskRun | None:
    return CreditRiskRun.query.filter_by(workflow_run_id=wf.id).first()


# ── Output builders ─────────────────────────────────────────────────────────────


def _model_predictions_df(wf: WorkflowRun) -> pd.DataFrame:
    """Union every target's backtest predictions (actual vs predicted), tagged
    with ``target`` and ``segment_key``. Segmented targets contribute one frame
    per successful segment; non-segmented targets contribute their run frame."""
    cals = CalibrationRun.query.filter_by(workflow_run_id=wf.id).all()
    frames = []
    for cal in cals:
        if cal.is_segmented:
            segs = CalibrationRunSegment.query.filter_by(
                calibration_run_id=cal.id, status="success"
            ).all()
            for seg in segs:
                sdf = calibration_service.segment_predictions_df(cal, seg.segment_key)
                if sdf is None or sdf.empty:
                    continue
                sdf = sdf.copy()
                sdf.insert(0, "segment_key", seg.segment_key)
                sdf.insert(0, "target", cal.target_col)
                frames.append(sdf)
        else:
            rdf = calibration_service.run_predictions_df(cal)
            if rdf is None or rdf.empty:
                continue
            rdf = rdf.copy()
            rdf.insert(0, "segment_key", None)
            rdf.insert(0, "target", cal.target_col)
            frames.append(rdf)

    if not frames:
        return pd.DataFrame(columns=["target", "segment_key", "actual", "predicted"])
    return pd.concat(frames, ignore_index=True, sort=False)


def _forecast_results_df(wf: WorkflowRun) -> pd.DataFrame:
    return workflow_service.combined_forecast_df(wf)


_CREDIT_LEAD_COLS = [
    "client_id",
    "sector",
    "subsector",
    "country",
    "segment_key",
    "SCENARIO",
    "YEAR",
]


def _credit_full_detail_df(wf: WorkflowRun) -> pd.DataFrame:
    """One row per client × year × scenario, merging each client's KMV row (PD,
    LGD, Rating, …) with the matching ECL row (ECL_12M, ECL_Lifetime, …)."""
    cr = _analysis_run(wf)
    if cr is None:
        return pd.DataFrame(columns=_CREDIT_LEAD_COLS)

    results = (
        CreditRiskResult.query.filter_by(run_id=cr.run_id)
        .order_by(CreditRiskResult.id)
        .all()
    )
    rows = []
    for r in results:
        kmv_rows = json.loads(r.kmv_json or "[]")
        ecl_rows = json.loads(r.ecl_json or "[]")
        ecl_by_key = {(e.get("YEAR"), e.get("SCENARIO")): e for e in ecl_rows}
        base = {
            "client_id": r.client_id,
            "sector": r.sector,
            "subsector": r.subsector,
            "country": r.country,
            "segment_key": r.segment_key,
        }
        seen = set()
        for k in kmv_rows:
            key = (k.get("YEAR"), k.get("SCENARIO"))
            merged = {**base, **k}
            e = ecl_by_key.get(key)
            if e:
                merged.update(
                    {kk: vv for kk, vv in e.items() if kk not in ("YEAR", "SCENARIO")}
                )
            rows.append(merged)
            seen.add(key)
        # ECL rows with no matching KMV year (defensive — shouldn't normally happen)
        for key, e in ecl_by_key.items():
            if key in seen:
                continue
            rows.append({**base, **e})

    if not rows:
        return pd.DataFrame(columns=_CREDIT_LEAD_COLS)
    df = pd.DataFrame.from_records(rows)
    lead = [c for c in _CREDIT_LEAD_COLS if c in df.columns]
    rest = [c for c in df.columns if c not in lead]
    return df[lead + rest]


# ── Output registry ─────────────────────────────────────────────────────────────
# key -> {label, description, perm (domain:action), builder(wf)->df, available(wf)->bool}

OUTPUTS: dict[str, dict] = {
    "model_predictions": {
        "label": "Model predictions",
        "description": "Backtest actual vs predicted for every target model.",
        "perm": "calibration:read",
        "builder": _model_predictions_df,
        "available": lambda wf: (
            CalibrationRun.query.filter_by(
                workflow_run_id=wf.id, status="success"
            ).first()
            is not None
        ),
    },
    "forecast_results": {
        "label": "Forecast results",
        "description": "Combined forecast across all targets, by date and segment.",
        "perm": "forecast:read",
        "builder": _forecast_results_df,
        "available": lambda wf: (
            ForecastRun.query.filter_by(workflow_run_id=wf.id, status="success").first()
            is not None
        ),
    },
    "credit_results": {
        "label": "Credit results (full detail)",
        "description": "Per-client KMV & ECL by year and scenario.",
        "perm": "credit_risk:read",
        "builder": _credit_full_detail_df,
        "available": lambda wf: (
            (cr := CreditRiskRun.query.filter_by(workflow_run_id=wf.id).first())
            is not None
            and cr.status == "success"
        ),
    },
}


def output_perm(output_key: str) -> str:
    spec = OUTPUTS.get(output_key)
    if not spec:
        raise NotFoundError(f"Unknown output: {output_key}")
    return spec["perm"]


# ── Reads ───────────────────────────────────────────────────────────────────────


def list_outputs(run_id: str) -> list[dict]:
    """The workflow's exportable outputs with availability (drives the tab list).

    Row counts are intentionally omitted here — they'd require building each
    (potentially huge) frame on every tab open. The exact count is recorded on
    each job once its file is built.
    """
    wf = _get_workflow(run_id)
    return [
        {
            "key": key,
            "label": spec["label"],
            "description": spec["description"],
            "perm": spec["perm"],
            "available": bool(spec["available"](wf)),
        }
        for key, spec in OUTPUTS.items()
    ]


def _job_dict(job: ExportJob, now: datetime | None = None) -> dict:
    now = _naive(now or _utcnow())
    d = job.to_dict()
    expired = bool(
        job.status == "success"
        and job.expires_at is not None
        and _naive(job.expires_at) < now
    )
    d["expired"] = expired
    d["downloadable"] = bool(
        job.status == "success" and job.object_path and not expired
    )
    return d


def get_export_job(job_id: str) -> dict:
    job = ExportJob.query.filter_by(job_id=job_id).first()
    if not job:
        raise NotFoundError("Export job not found")
    return _job_dict(job)


def list_export_jobs(run_id: str) -> list[dict]:
    wf = _get_workflow(run_id)
    now = _utcnow()
    jobs = (
        ExportJob.query.filter_by(workflow_run_id=wf.id)
        .order_by(ExportJob.created_at.desc())
        .all()
    )
    return [_job_dict(j, now) for j in jobs]


def get_download_target(run_id: str, job_id: str) -> ExportJob:
    """Resolve a job for the download route. Raises ``NotFoundError`` (missing or
    expired) / ``BadRequestError`` (not ready / failed)."""
    wf = _get_workflow(run_id)
    job = ExportJob.query.filter_by(job_id=job_id, workflow_run_id=wf.id).first()
    if not job:
        raise NotFoundError("Export job not found")
    if job.status != "success" or not job.object_path:
        raise BadRequestError("Export is not ready to download yet")
    if job.expires_at is not None and _naive(job.expires_at) < _naive(_utcnow()):
        raise NotFoundError("This export has expired — please generate it again")
    return job


# ── Job creation + build ────────────────────────────────────────────────────────


def create_export_job(
    run_id: str, output_key: str, fmt: str, user_email: str | None
) -> dict:
    """Create (or reuse) an export job for one output+format. Validates the
    output/format/availability. Dedupes against an in-flight or fresh successful
    job. The caller commits, then dispatches ``export_dataset``."""
    if output_key not in OUTPUTS:
        raise BadRequestError(f"Unknown output: {output_key}")
    if fmt not in tabular_export.FORMATS:
        raise BadRequestError(f"Unsupported export format: {fmt}")

    wf = _get_workflow(run_id)
    if not OUTPUTS[output_key]["available"](wf):
        raise BadRequestError("This output is not ready to export yet")

    now = _naive(_utcnow())
    existing = (
        ExportJob.query.filter_by(workflow_run_id=wf.id, output_key=output_key, fmt=fmt)
        .filter(ExportJob.status.in_((*ACTIVE_STATUSES, "success")))
        .order_by(ExportJob.created_at.desc())
        .first()
    )
    if existing and (
        existing.status in ACTIVE_STATUSES
        or (existing.expires_at is not None and _naive(existing.expires_at) > now)
    ):
        return _job_dict(existing)

    job_id = str(uuid.uuid4())
    with app_session() as s:
        job = ExportJob(
            job_id=job_id,
            workflow_run_id=wf.id,
            output_key=output_key,
            fmt=fmt,
            status="queued",
            progress=0,
            triggered_by=user_email,
            created_at=_utcnow(),
        )
        s.add(job)
        s.flush()
        result = _job_dict(job)
    return result


def _sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "").strip()).strip("_") or "export"


def build_export_bytes(
    run_id: str, output_key: str, fmt: str
) -> tuple[bytes, str, str, int]:
    """Build one output's full DataFrame and encode it. Returns
    ``(data, filename, mimetype, row_count)``. Used by the export worker."""
    spec = OUTPUTS.get(output_key)
    if not spec:
        raise BadRequestError(f"Unknown output: {output_key}")
    wf = _get_workflow(run_id)
    df = spec["builder"](wf)
    data, mimetype = tabular_export.dataframe_to_bytes(df, fmt)
    ts = _utcnow().strftime("%Y%m%d-%H%M")
    filename = f"{_sanitize(wf.name or run_id)}_{output_key}_{ts}.{fmt}"
    return data, filename, mimetype, int(len(df))


def object_prefix(wf_run_id: str, job_id: str) -> str:
    """MinIO key prefix (no bucket) for one job's file(s)."""
    return f"exports/{wf_run_id}/{job_id}/"


# ── Cleanup ─────────────────────────────────────────────────────────────────────


def retention_expiry(now: datetime | None = None) -> datetime:
    return (now or _utcnow()) + timedelta(hours=EXPORT_RETENTION_HOURS)


def purge_expired(now: datetime | None = None) -> int:
    """Delete every expired job's MinIO file and row. Returns the count removed."""
    now_naive = _naive(now or _utcnow())
    expired = ExportJob.query.filter(
        ExportJob.expires_at.isnot(None), ExportJob.expires_at < now_naive
    ).all()
    if not expired:
        return 0

    prefixes = []
    ids = []
    for job in expired:
        ids.append(job.id)
        if job.object_path:
            key = job.object_path.split("/", 1)[-1]  # strip "{bucket}/"
            prefixes.append(key.rsplit("/", 1)[0] + "/")

    with app_session():
        ExportJob.query.filter(ExportJob.id.in_(ids)).delete(synchronize_session=False)

    for prefix in prefixes:
        storage.remove_prefix(prefix)
    return len(ids)
