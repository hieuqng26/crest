import io
import json
import pickle
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from project.constants import Progress
from project.core import storage
from project.workers import celery_app
from project.workers.common import (
    _make_flask_app,
    _split_segment_key,
    _write_forecast_progress,
    format_failure,
)


from project.logger import get_logger

logger = get_logger(__name__)


def _score_segment_against_df(
    df: "pd.DataFrame", seg_artifact_path: str, seg_key: str
) -> tuple[list, list]:
    """Score one segment's pickled model against every row of `df`.

    Returns (predicted_list, meta_rows) where meta_rows are per-row dicts of
    non-feature columns, each tagged with `segment_key` so credit-risk analysis can
    later route each client to the matching segment. Pure: reads the artifact from
    MinIO, writes nothing. Shared by run_forecast (full-run scoring) and
    recompute_forecast_run_segment (per-segment re-score).
    """
    seg_bytes = storage.download_bytes(seg_artifact_path.split("/", 1)[-1])
    seg_artifact = pickle.loads(seg_bytes)  # noqa: S301
    feature_cols = seg_artifact["feature_cols"]
    missing_cols = [c for c in feature_cols if c not in df.columns]
    if missing_cols:
        raise ValueError(
            f"Forecast dataset missing required feature columns for "
            f"segment '{seg_key}': {missing_cols}"
        )
    X_df = df[feature_cols].select_dtypes(include=[np.number])
    actual_feature_cols = list(X_df.columns)
    non_numeric = [c for c in feature_cols if c not in actual_feature_cols]
    if non_numeric:
        raise ValueError(
            f"Feature columns are not numeric in forecast dataset: {non_numeric}"
        )
    X = X_df.values
    if seg_artifact["scaler"]:
        X = seg_artifact["scaler"].transform(X)
    preds = seg_artifact["model"].predict(X)

    meta_cols = [c for c in df.columns if c not in set(actual_feature_cols)]
    meta_rows = df[meta_cols].to_dict("records")
    for r in meta_rows:
        r["segment_key"] = seg_key

    predicted = [float(v) if v is not None else None for v in preds.tolist()]
    return predicted, meta_rows


def _forecast_result_mappings(fr_id: int, predicted_list, meta_rows, segment_key):
    """Build ForecastRunResult insert-mappings from a parallel predicted/meta pair.

    Mirrors the full-run bulk-insert shape (date/predicted/meta_json) and adds the
    denormalised `segment_key` column. `_coerce` normalises numpy scalars to plain
    Python so json.dumps and the ORM accept them.
    """

    def _coerce(v):
        if v is None or isinstance(v, (str, bool)):
            return v
        if isinstance(v, (float, np.floating)):
            return float(v)
        if isinstance(v, (int, np.integer)):
            return int(v)
        return str(v)

    dates_list = [r.get("date") for r in meta_rows]
    other_keys_set: set[str] = set()
    for r in meta_rows:
        other_keys_set.update(k for k in r if k != "date")
    other_keys = sorted(other_keys_set)
    meta_dict = {k: [_coerce(r.get(k)) for r in meta_rows] for k in other_keys}

    from project.services.forecast_runs import promoted_dims_from_meta

    rows = []
    for i in range(len(predicted_list)):
        row_meta = {k: meta_dict[k][i] for k in other_keys}
        rows.append(
            {
                "forecast_run_id": fr_id,
                "date": str(dates_list[i]) if dates_list[i] is not None else None,
                "predicted": predicted_list[i],
                "meta_json": json.dumps(row_meta) if other_keys else None,
                "segment_key": segment_key,
                **{
                    k: v
                    for k, v in promoted_dims_from_meta(row_meta).items()
                    if k != "segment_key"  # segment_key set explicitly above
                },
            }
        )
    return rows


def recompute_forecast_run_segment(
    s, fr, df: "pd.DataFrame", seg_artifact_path: str, segment_key: str
) -> int:
    """Delete THIS run's ForecastRunResult rows for `segment_key`, re-score just that
    segment against `df`, and bulk-insert fresh rows into the SAME run. Returns the
    number of rows written. Caller owns the session/transaction, so the delete +
    insert is one atomic swap — readers never see the segment mid-swap.
    """
    from project.db_models.forecast_models import ForecastRunResult

    ForecastRunResult.query.filter_by(
        forecast_run_id=fr.id, segment_key=segment_key
    ).delete(synchronize_session=False)
    predicted_list, meta_rows = _score_segment_against_df(
        df, seg_artifact_path, segment_key
    )
    mappings = _forecast_result_mappings(fr.id, predicted_list, meta_rows, segment_key)
    if mappings:
        s.bulk_insert_mappings(ForecastRunResult, mappings)
    return len(mappings)


@celery_app.task(bind=True, name="run_forecast")
def run_forecast(self, run_id: str):
    from project.workers.workflow import (
        advance_workflow,
    )  # deferred: avoids import cycle

    app = _make_flask_app()
    with app.app_context():
        import pickle

        from project import app_session
        from project.db_models.calibration_models import CalibrationRun, Dataset
        from project.db_models.forecast_models import ForecastRun, ForecastRunResult

        fr0 = ForecastRun.query.filter_by(run_id=run_id).first()
        if not fr0:
            logger.error(f"ForecastRun {run_id} not found")
            return
        if fr0.status == "failed":
            # Cancelled while queued — a worker picked it up after the fact.
            return
        workflow_run_id = fr0.workflow_run_id

        try:
            # Load all needed DB values as plain scalars before any session closes.
            # Validation raises (missing cal_run/dataset) are inside this try so the
            # run always reaches a terminal status — never stuck at "queued"/"running".
            with app_session() as s:
                fr = ForecastRun.query.filter_by(run_id=run_id).first()
                cal_run = CalibrationRun.query.get(fr.calibration_run_id)
                ds = Dataset.query.get(fr.dataset_id)
                if not cal_run:
                    raise ValueError("Calibration run not found")
                if not ds or not ds.file_path:
                    raise ValueError(
                        f"Dataset {fr.dataset_id} not found or has no file"
                    )
                cal_run_id_int = cal_run.id
                artifact_path = cal_run.artifact_path
                is_segmented = cal_run.seg_sectors_json is not None
                segment_key = fr.segment_key
                ds_file_path = ds.file_path
                fr.status = "running"
                fr.started_at = datetime.now(timezone.utc)
                s.add(fr)
            if workflow_run_id:
                advance_workflow.delay(workflow_run_id)

            _write_forecast_progress(run_id, 5, "Loading forecast dataset…")

            file_bytes = storage.download_bytes(ds_file_path.split("/", 1)[-1])
            ext = ds_file_path.rsplit(".", 1)[-1].lower()
            buf = io.BytesIO(file_bytes)
            if ext == "csv":
                df = pd.read_csv(buf)
            elif ext == "xlsx":
                df = pd.read_excel(buf)
            elif ext == "parquet":
                df = pd.read_parquet(buf)
            else:
                raise ValueError(f"Unsupported file type: {ext}")

            _write_forecast_progress(
                run_id, 20, f"Loaded {len(df):,} rows · {len(df.columns)} columns"
            )

            def _coerce(v):
                if v is None or isinstance(v, (str, bool)):
                    return v
                if isinstance(v, float):
                    return float(v)
                if isinstance(v, (int, np.integer)):
                    return int(v)
                return str(v)

            def _score_segment(
                seg_artifact_path: str, seg_key: str
            ) -> tuple[list, list]:
                # Thin wrapper over the module-level scorer, bound to this run's df.
                return _score_segment_against_df(df, seg_artifact_path, seg_key)

            if segment_key:
                # Score one named segment against the whole forecast dataset.
                from project.db_models.calibration_models import CalibrationRunSegment

                seg_sector, seg_split = _split_segment_key(segment_key)
                _write_forecast_progress(
                    run_id,
                    30,
                    f"Loading segment artifact for '{segment_key}'…",
                    sector=seg_sector,
                    segment=seg_split,
                )
                seg = CalibrationRunSegment.query.filter_by(
                    calibration_run_id=cal_run_id_int,
                    segment_key=segment_key,
                    status="success",
                ).first()
                if not seg:
                    raise ValueError(
                        f"Segment '{segment_key}' not found or has not succeeded"
                    )
                # Extract the scalar now — _write_forecast_progress() closes db.session,
                # which would expire/detach this ORM object before we read its attribute.
                seg_artifact_path = seg.artifact_path
                _write_forecast_progress(
                    run_id,
                    45,
                    "Preparing features…",
                    sector=seg_sector,
                    segment=seg_split,
                )
                predicted_list, meta_rows = _score_segment(
                    seg_artifact_path, segment_key
                )
                _write_forecast_progress(
                    run_id,
                    60,
                    "Applied segment model",
                    sector=seg_sector,
                    segment=seg_split,
                )

            elif is_segmented:
                # Score every trained segment against the whole (MEV-only,
                # portfolio-wide) forecast dataset — one trajectory per segment.
                # Credit risk analysis applies the matching segment's trajectory to
                # each client based on that client's own sector/subsector/country.
                from project.db_models.calibration_models import CalibrationRunSegment

                _write_forecast_progress(run_id, 30, "Loading segment manifests…")
                segments = CalibrationRunSegment.query.filter_by(
                    calibration_run_id=cal_run_id_int, status="success"
                ).all()
                if not segments:
                    raise ValueError(
                        "No successful segments found for this calibration run"
                    )
                # Extract scalars now — _write_forecast_progress() closes db.session,
                # which would expire/detach these ORM objects before we read them below.
                segment_refs = [(s.artifact_path, s.segment_key) for s in segments]

                _write_forecast_progress(
                    run_id,
                    35,
                    f"Scoring {len(df):,} forecast rows with {len(segment_refs)} segment "
                    "models — credit risk applies the matching segment per client.",
                )
                predicted_list = []
                meta_rows = []
                for i, (seg_artifact_path, seg_key) in enumerate(segment_refs):
                    seg_preds, seg_meta_rows = _score_segment(
                        seg_artifact_path, seg_key
                    )
                    predicted_list.extend(seg_preds)
                    meta_rows.extend(seg_meta_rows)
                    seg_sector, seg_split = _split_segment_key(seg_key)
                    _write_forecast_progress(
                        run_id,
                        35 + round(55 * (i + 1) / len(segment_refs)),
                        f"Scored segment '{seg_key}' ({i + 1}/{len(segment_refs)})",
                        sector=seg_sector,
                        segment=seg_split,
                    )

            else:
                if not artifact_path:
                    raise ValueError("Calibration run artifact not found")
                _write_forecast_progress(
                    run_id, 30, "Loading calibration model artifact…"
                )
                artifact_bytes = storage.download_bytes(artifact_path.split("/", 1)[-1])
                artifact = pickle.loads(artifact_bytes)  # noqa: S301
                plugin = artifact["model"]
                scaler = artifact["scaler"]
                feature_cols = artifact["feature_cols"]

                missing_cols = [c for c in feature_cols if c not in df.columns]
                if missing_cols:
                    raise ValueError(
                        f"Forecast dataset is missing required feature columns: {missing_cols}"
                    )

                _write_forecast_progress(run_id, 40, "Preparing features…")
                X_df = df[feature_cols].select_dtypes(include=[np.number])
                actual_feature_cols = list(X_df.columns)
                missing_numeric = [
                    c for c in feature_cols if c not in actual_feature_cols
                ]
                if missing_numeric:
                    raise ValueError(
                        f"Feature columns are not numeric in forecast dataset: {missing_numeric}"
                    )
                X = X_df.values
                if scaler:
                    X = scaler.transform(X)

                _write_forecast_progress(run_id, 55, "Applying model…")
                predicted_arr = plugin.predict(X)
                predicted_list = [
                    float(v) if v is not None else None for v in predicted_arr.tolist()
                ]
                meta_col_set = set(actual_feature_cols)
                meta_cols = [c for c in df.columns if c not in meta_col_set]
                meta_rows = df[meta_cols].to_dict("records")

            dates_list = [r.get("date") for r in meta_rows]
            other_keys_set: set[str] = set()
            for r in meta_rows:
                other_keys_set.update(k for k in r if k != "date")
            other_keys = sorted(other_keys_set)
            meta_dict = {k: [_coerce(r.get(k)) for r in meta_rows] for k in other_keys}

            _write_forecast_progress(run_id, 70, "Storing predictions…")

            with app_session() as s:
                r = ForecastRun.query.filter_by(run_id=run_id).first()
                # segment_key is present in meta only for segmented runs; NULL otherwise.
                seg_key_col = meta_dict.get("segment_key")

                from project.services.forecast_runs import promoted_dims_from_meta

                result_rows = []
                for i in range(len(predicted_list)):
                    row_meta = {k: meta_dict[k][i] for k in other_keys}
                    result_rows.append(
                        {
                            "forecast_run_id": r.id,
                            "date": str(dates_list[i])
                            if dates_list[i] is not None
                            else None,
                            "predicted": predicted_list[i],
                            "meta_json": json.dumps(row_meta) if other_keys else None,
                            "segment_key": seg_key_col[i] if seg_key_col else None,
                            **{
                                k: v
                                for k, v in promoted_dims_from_meta(row_meta).items()
                                if k != "segment_key"
                            },
                        }
                    )
                s.bulk_insert_mappings(ForecastRunResult, result_rows)
                r.status = "success"
                r.finished_at = datetime.now(timezone.utc)
                r.progress = 100
                s.add(r)

            _write_forecast_progress(run_id, 100, "Forecast completed successfully")
            if workflow_run_id:
                advance_workflow.delay(workflow_run_id)

        except Exception as exc:
            logger.error(f"Forecast run {run_id} failed: {exc}", exc_info=True)
            with app_session() as s:
                r = ForecastRun.query.filter_by(run_id=run_id).first()
                if r:
                    r.status = "failed"
                    r.finished_at = datetime.now(timezone.utc)
                    r.error_message = format_failure(exc)
                    s.add(r)
            _write_forecast_progress(run_id, Progress.FAILED, f"Failed: {exc}")
            if workflow_run_id:
                advance_workflow.delay(workflow_run_id)
            raise
