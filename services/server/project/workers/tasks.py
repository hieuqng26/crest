import io
import itertools
import json
import pickle
import random
import traceback
import uuid
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_squared_error,
    r2_score,
    roc_auc_score,
)
from sklearn.model_selection import KFold, StratifiedKFold, train_test_split
from sklearn.preprocessing import MinMaxScaler, RobustScaler, StandardScaler

from project.constants import Progress
from project.core import dataset_io, storage
from project.core.model_registry import get_model_class
from project.logger import get_logger
from project.workers import celery_app
from project.workers.context import worker_session

_TRACEBACK_LIMIT = 20000


def format_failure(exc: BaseException, limit: int = _TRACEBACK_LIMIT) -> str:
    """Render the full traceback for persistence in a run's ``error_message``.

    The architecture contract is that a failed run keeps its traceback (not
    just ``str(exc)``) so failures are diagnosable from the run row alone. The
    tail is kept when the trace exceeds ``limit`` — the innermost frames (where
    the error actually occurred) are the most useful.
    """
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return tb[-limit:]


def _load_forecast_data(forecast) -> dict:
    """Load forecast payload — forecast_results rows for new runs, forecast_json fallback for old."""
    from project.db_models.calibration_models import ForecastResult

    # Fetch rows once and branch on the result — the old `results.count() > 0`
    # pre-check issued a second COUNT query on top of the same lazy relationship.
    rows = forecast.results.order_by(ForecastResult.id).all()
    if rows:
        actual = [r.actual for r in rows]
        predicted = [r.predicted for r in rows]
        client_id = [r.client_id for r in rows]
        date = [r.date for r in rows]
        meta_rows = [json.loads(r.meta_json or "{}") for r in rows]
        other_keys: set[str] = set()
        for m in meta_rows:
            other_keys.update(m.keys())
        meta: dict[str, list] = {k: [m.get(k) for m in meta_rows] for k in other_keys}
        if any(v is not None for v in client_id):
            meta["client_id"] = client_id
        if any(v is not None for v in date):
            meta["date"] = date
        return {"actual": actual, "predicted": predicted, "meta": meta}
    return json.loads(forecast.forecast_json or "{}")


logger = get_logger(__name__)


def _make_flask_app():
    from project import create_app

    return create_app()


def _get_scaler(name: str):
    return {
        "standard": StandardScaler(),
        "minmax": MinMaxScaler(),
        "robust": RobustScaler(),
    }.get(name)


def _split_segment_key(segment_key: str | None) -> tuple[str | None, str | None]:
    """Split a "{sector}__{split_value}" segment key into (sector, segment)."""
    if not segment_key or "__" not in segment_key:
        return None, None
    sector, split_value = segment_key.split("__", 1)
    return sector, split_value


def _cal_log(
    run_id: str,
    message: str,
    level: str = "info",
    sector: str | None = None,
    segment: str | None = None,
):
    """Write a CalibrationRunLog line WITHOUT touching the run's progress.

    Used for segment re-fits, which log against an already-complete parent run
    (progress 100) that must not be rewound. Silent-fails like _write_progress."""
    try:
        from project.db_models.calibration_models import CalibrationRunLog

        # worker_session() so this write never expires ORM objects the task holds.
        with worker_session() as s:
            s.add(
                CalibrationRunLog(
                    run_id=run_id,
                    logged_at=datetime.now(timezone.utc),
                    level=level,
                    message=message,
                    sector=sector,
                    segment=segment,
                )
            )
    except Exception as _e:
        logger.warning(f"_cal_log failed: {_e}")


def _write_progress(
    run_id: str,
    progress: int,
    message: str,
    sector: str | None = None,
    segment: str | None = None,
):
    """Write progress + a log line to DB. Always silent-fails so calibration is never blocked.

    ``sector``/``segment`` tag a segment-scoped line so the unified workflow log
    view can filter by them; leave them None for general lines."""
    try:
        from project.db_models.calibration_models import (
            CalibrationRun,
            CalibrationRunLog,
        )

        level = (
            "error"
            if progress < 0
            else ("warn" if "warn" in message.lower() else "info")
        )
        # worker_session() so this write never expires ORM objects the task holds.
        with worker_session() as s:
            r = s.query(CalibrationRun).filter_by(run_id=run_id).first()
            if r:
                r.progress = max(0, progress)
                r.progress_message = message
            s.add(
                CalibrationRunLog(
                    run_id=run_id,
                    logged_at=datetime.now(timezone.utc),
                    level=level,
                    message=message,
                    sector=sector,
                    segment=segment,
                )
            )
    except Exception:
        # Progress/log writes must never kill a run, but a silent failure hides
        # real DB problems — log it instead of swallowing outright.
        logger.exception("_write_progress failed for run %s", run_id)


def _cv_search(
    plugin_cls,
    base_params: dict,
    search_cfg: dict,
    X_train,
    y_train,
    run_id: str,
    sector: str | None = None,
    segment: str | None = None,
) -> dict:
    """
    Run grid or randomised cross-validated hyperparameter search.

    search_cfg keys:
      type        : "grid" | "random"
      param_grid  : {param: [values, ...]}
      cv          : number of folds (default 5)
      scoring     : "roc_auc" | "accuracy" | "neg_mean_squared_error" (default "roc_auc")
      n_iter      : candidates to sample when type="random" (default 20)

    Returns {"best_params": {...}, "cv_results": [...]}
    """
    param_grid = search_cfg.get("param_grid", {})
    search_type = search_cfg.get("type", "grid")
    n_folds = int(search_cfg.get("cv", 5))
    scoring = search_cfg.get("scoring", "roc_auc")
    n_iter = int(search_cfg.get("n_iter", 20))

    # Build candidate list
    keys = list(param_grid.keys())
    combos = list(itertools.product(*[param_grid[k] for k in keys]))
    if search_type == "random" and len(combos) > n_iter:
        combos = random.sample(combos, n_iter)

    # Choose CV splitter — stratified only when scoring involves AUC/accuracy (binary)
    use_stratified = scoring in ("roc_auc", "accuracy", "f1")
    unique_classes = np.unique(y_train)
    can_stratify = use_stratified and len(unique_classes) == 2

    def make_cv():
        return (
            StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=42)
            if can_stratify
            else KFold(n_splits=n_folds, shuffle=True, random_state=42)
        )

    def score_fold(model, Xv, yv):
        preds = model.predict(Xv)
        if scoring == "roc_auc":
            return float(roc_auc_score(yv, preds))
        if scoring == "accuracy":
            return float(accuracy_score(yv, preds))
        if scoring == "f1":
            return float(f1_score(yv, preds))
        if scoring == "neg_mean_squared_error":
            return -float(mean_squared_error(yv, preds))
        if scoring == "r2":
            return float(r2_score(yv, preds))
        raise ValueError(f"Unknown scoring: {scoring}")

    cv_results = []
    best_score = None
    best_params = dict(base_params)

    total = len(combos)
    for idx, combo in enumerate(combos):
        candidate = dict(zip(keys, combo))
        merged = {**base_params, **candidate}

        fold_scores = []
        try:
            params_obj = plugin_cls.param_schema(**merged)
            for train_idx, val_idx in make_cv().split(
                X_train, y_train if can_stratify else None
            ):
                Xf, Xv = X_train[train_idx], X_train[val_idx]
                yf, yv = y_train[train_idx], y_train[val_idx]
                p = plugin_cls()
                p.fit(Xf, yf, params_obj)
                fold_scores.append(score_fold(p, Xv, yv))
        except Exception as exc:
            logger.warning(f"CV candidate {candidate} failed: {exc}")
            cv_results.append(
                {"params": candidate, "mean_score": None, "error": str(exc)}
            )
            continue

        mean_score = float(np.mean(fold_scores))
        std_score = float(np.std(fold_scores))
        cv_results.append(
            {"params": candidate, "mean_score": mean_score, "std_score": std_score}
        )

        if best_score is None or mean_score > best_score:
            best_score = mean_score
            best_params = merged

        _write_progress(
            run_id,
            35 + int(15 * (idx + 1) / total),
            f"CV search {idx + 1}/{total} · best {scoring}={best_score:.4f}",
            sector=sector,
            segment=segment,
        )

    return {
        "best_params": best_params,
        "cv_results": cv_results,
        "best_score": best_score,
    }


def _resolve_sector_training_config(
    sector: str,
    overrides: dict,
    default_split_by: str,
    default_max_segments: int,
    default_feature_cols: list,
    default_model_config_id: int,
    resolved_configs: dict[int, tuple[str, dict, str]],
) -> dict:
    """Resolve one sector's effective training config from its override entry
    (if any) plus the run-level defaults. resolved_configs maps
    model_config_id -> (algorithm, raw_params, model_family), pre-fetched for
    every config id referenced anywhere (default + all overrides) so this
    function never touches the DB — call it only after that pre-fetch.
    """
    o = overrides.get(sector, {})
    split_by = o.get("split_by") or default_split_by
    max_segments = o.get("max_segments") or default_max_segments
    feature_cols = o["feature_cols"] if "feature_cols" in o else default_feature_cols
    cfg_id = o.get("model_config_id") or default_model_config_id
    algorithm, raw_params, model_family = resolved_configs[cfg_id]
    # Hyperparameter search is tuned for the run's default algorithm's
    # parameter names; skip it for sectors overriding to a different model so
    # we never grid-search over parameter names that belong to a different
    # algorithm.
    use_search = cfg_id == default_model_config_id
    return {
        "split_by": split_by,
        "max_segments": max_segments,
        "feature_cols": feature_cols,
        "model_config_id": cfg_id,
        "algorithm": algorithm,
        "raw_params": dict(raw_params),
        "model_family": model_family,
        "use_search": use_search,
    }


def _sector_split_groups(
    df_sector: "pd.DataFrame", split_col: str, max_seg: int
) -> dict[str, "pd.DataFrame"] | None:
    """Rank one sector's rows by split_col into up to max_seg groups (by total EAD,
    or row count if no ead column) plus an 'Others' bucket for the rest. Returns
    None if split_col isn't present. Used by both the initial segmented run and a
    single-segment re-run so they reproduce the exact same grouping."""
    if split_col not in df_sector.columns:
        return None

    if "ead" in df_sector.columns:
        ead_ranks = (
            df_sector.groupby(split_col)["ead"].sum().sort_values(ascending=False)
        )
    else:
        ead_ranks = df_sector.groupby(split_col).size().sort_values(ascending=False)

    top_values = list(ead_ranks.index[:max_seg])
    rest_values = list(ead_ranks.index[max_seg:])

    groups: dict[str, pd.DataFrame] = {
        v: df_sector[df_sector[split_col] == v] for v in top_values
    }
    if rest_values:
        groups["Others"] = df_sector[df_sector[split_col].isin(rest_values)]
    return groups


def _fit_segment(
    df_group: "pd.DataFrame",
    algorithm: str,
    raw_params: dict,
    search_cfg,
    train_split_ratio: float,
    scaler_name,
    target_col: str,
    feature_cols_json: list,
    model_family: str,
    artifact_key: str,
    run_id: str,
    sector: str | None = None,
    segment: str | None = None,
) -> tuple[dict, dict, str]:
    """Fit one model on df_group, save artifact to MinIO, return (val_metrics, train_metrics, artifact_path).

    ``sector``/``segment`` tag this segment's CV-search progress lines in the log."""
    candidate_cols = feature_cols_json or [
        c for c in df_group.columns if c != target_col
    ]
    X_df = df_group[candidate_cols].select_dtypes(include=[np.number])
    feature_cols = list(X_df.columns)
    X = X_df.values
    y = df_group[target_col].values

    idx = np.arange(len(df_group))
    idx_train, idx_val = train_test_split(
        idx, test_size=round(1.0 - train_split_ratio, 4), random_state=42
    )
    X_train, X_val = X[idx_train], X[idx_val]
    y_train, y_val = y[idx_train], y[idx_val]

    scaler = _get_scaler(scaler_name)
    if scaler:
        X_train = scaler.fit_transform(X_train)
        X_val = scaler.transform(X_val)

    plugin_cls = get_model_class(algorithm)
    plugin = plugin_cls()

    if search_cfg and search_cfg.get("param_grid"):
        search_result = _cv_search(
            plugin_cls,
            raw_params,
            search_cfg,
            X_train,
            y_train,
            run_id,
            sector=sector,
            segment=segment,
        )
        raw_params = search_result["best_params"]

    params_obj = plugin_cls.param_schema(**raw_params)
    plugin.fit(X_train, y_train, params_obj)

    diag = plugin.diagnostics(X_val, y_val)
    for key in ("feature_importance", "coef_table"):
        if key in diag and feature_cols:
            for i, entry in enumerate(diag[key]):
                if i < len(feature_cols):
                    entry["feature"] = feature_cols[i]

    # Per-observation validation data for backtesting UI (mirrors non-segmented path)
    def _cv(v):
        if v is None or isinstance(v, (str, bool)):
            return v
        if isinstance(v, (float, np.floating)):
            return float(v)
        if isinstance(v, (int, np.integer)):
            return int(v)
        return str(v)

    y_val_pred = plugin.predict(X_val)
    df_val_group = df_group.iloc[idx_val].reset_index(drop=True)
    meta_col_set = set(candidate_cols) | {target_col}
    meta_cols_val = [c for c in df_val_group.columns if c not in meta_col_set]
    diag["val_obs"] = {
        "actual": [_cv(v) for v in y_val.tolist()],
        "predicted": [_cv(v) for v in y_val_pred.tolist()],
        "meta": {
            col: [_cv(v) for v in df_val_group[col].tolist()] for col in meta_cols_val
        },
    }

    y_train_pred = plugin.predict(X_train)
    try:
        if model_family == "classification":
            train_metrics = {"auc_roc": float(roc_auc_score(y_train, y_train_pred))}
        else:
            train_metrics = {
                "r2": float(r2_score(y_train, y_train_pred)),
                "rmse": float(np.sqrt(mean_squared_error(y_train, y_train_pred))),
            }
    except Exception:
        train_metrics = {}

    artifact_bytes = pickle.dumps(
        {"model": plugin, "scaler": scaler, "feature_cols": feature_cols}
    )
    artifact_path = storage.upload_bytes(
        artifact_key, artifact_bytes, "application/octet-stream"
    )

    return diag, train_metrics, artifact_path


@celery_app.task(bind=True, name="run_calibration")
def run_calibration(self, run_id: str):
    app = _make_flask_app()
    with app.app_context():
        from project import app_session
        from project.db_models.calibration_models import (
            CalibrationRun,
            Dataset,
            Forecast,
            ModelConfig,
        )

        # --- 0. Verify run exists and grab foreign-key IDs before any session closes ---
        initial = CalibrationRun.query.filter_by(run_id=run_id).first()
        if not initial:
            logger.error(f"CalibrationRun {run_id} not found")
            return
        if initial.status == "failed":
            # Cancelled while queued — a worker picked it up after the fact.
            return
        initial_workflow_run_id = initial.workflow_run_id
        dataset_id = initial.dataset_id
        model_config_id = initial.model_config_id
        search_config_json = initial.search_config_json
        train_split_ratio = (
            initial.train_split if initial.train_split is not None else 0.8
        )
        scaler_name = initial.scaler
        initial_target_col = initial.target_col
        initial_feature_cols_json = initial.feature_cols_json
        initial_seg_sectors_json = initial.seg_sectors_json
        initial_seg_split_by = initial.seg_split_by
        initial_seg_max_segments = initial.seg_max_segments
        initial_seg_sector_overrides_json = initial.seg_sector_overrides_json

        try:
            # --- 1. Mark running ---
            with app_session() as s:
                r = CalibrationRun.query.filter_by(run_id=run_id).first()
                r.status = "running"
                r.started_at = datetime.now(timezone.utc)
                s.add(r)
            _write_progress(run_id, 5, "Loading dataset…")
            if initial_workflow_run_id:
                advance_workflow.delay(initial_workflow_run_id)

            # --- 2. Load dataset + config ---
            ds = Dataset.query.get(dataset_id)
            cfg = ModelConfig.query.get(model_config_id)
            model_family = cfg.family  # extract before session can close

            sector_overrides = json.loads(initial_seg_sector_overrides_json or "{}")
            override_cfg_ids = {
                v["model_config_id"]
                for v in sector_overrides.values()
                if v.get("model_config_id")
            }
            resolved_configs: dict[int, tuple[str, dict, str]] = {
                model_config_id: (
                    cfg.algorithm,
                    json.loads(cfg.hyperparams_json or "{}"),
                    model_family,
                )
            }
            for cid in override_cfg_ids - {model_config_id}:
                override_cfg = ModelConfig.query.get(cid)
                if not override_cfg:
                    raise ValueError(f"Model configuration {cid} not found")
                resolved_configs[cid] = (
                    override_cfg.algorithm,
                    json.loads(override_cfg.hyperparams_json or "{}"),
                    override_cfg.family,
                )

            if not ds.file_path:
                raise ValueError(
                    "No file path on dataset — live query results must be cached first"
                )

            file_bytes = storage.download_bytes(ds.file_path.split("/", 1)[-1])
            ext = ds.file_path.rsplit(".", 1)[-1].lower()
            buf = io.BytesIO(file_bytes)
            if ext == "csv":
                df = pd.read_csv(buf)
            elif ext == "xlsx":
                df = pd.read_excel(buf)
            elif ext == "parquet":
                df = pd.read_parquet(buf)
            else:
                raise ValueError(f"Unsupported file type: {ext}")

            target_col = initial_target_col or ""
            algorithm = cfg.algorithm
            raw_params = json.loads(cfg.hyperparams_json or "{}")
            feature_cols_json = json.loads(initial_feature_cols_json or "[]")
            search_cfg = json.loads(search_config_json or "null")

            _write_progress(
                run_id, 20, f"Loaded {len(df):,} rows · {len(df.columns)} columns"
            )

            # --- 2b. Segmented or single-model path ---
            if initial_seg_sectors_json:
                from project.db_models.calibration_models import CalibrationRunSegment

                seg_sectors = json.loads(initial_seg_sectors_json)
                default_split = initial_seg_split_by
                default_max = initial_seg_max_segments
                min_rows = 10

                if "sector" not in df.columns:
                    raise ValueError(
                        "Dataset must contain a 'sector' column for segmented calibration"
                    )

                df_seg = df[df["sector"].isin(seg_sectors)]
                total_sectors = len(seg_sectors)
                processed = 0
                for sector, df_sector in df_seg.groupby("sector"):
                    sector_cfg = _resolve_sector_training_config(
                        sector,
                        sector_overrides,
                        default_split,
                        default_max,
                        feature_cols_json,
                        model_config_id,
                        resolved_configs,
                    )
                    split_col = sector_cfg["split_by"]
                    max_seg = sector_cfg["max_segments"]

                    groups = _sector_split_groups(df_sector, split_col, max_seg)
                    if groups is None:
                        logger.warning(
                            f"Sector '{sector}': split column '{split_col}' not found, skipping"
                        )
                        continue

                    for split_value, df_group in groups.items():
                        seg_key = f"{sector}__{split_value}"
                        seg_status = "success"
                        seg_error = None
                        seg_artifact_path = None
                        seg_train_metrics = None
                        seg_val_metrics = None
                        seg_ead = (
                            float(df_group["ead"].sum())
                            if "ead" in df_group.columns
                            else None
                        )

                        if len(df_group) < min_rows:
                            seg_status = "skipped"
                            seg_error = f"Only {len(df_group)} rows (min {min_rows})"
                        else:
                            try:
                                (
                                    seg_val_metrics,
                                    seg_train_metrics,
                                    seg_artifact_path,
                                ) = _fit_segment(
                                    df_group,
                                    sector_cfg["algorithm"],
                                    sector_cfg["raw_params"],
                                    search_cfg if sector_cfg["use_search"] else None,
                                    train_split_ratio,
                                    scaler_name,
                                    target_col,
                                    sector_cfg["feature_cols"],
                                    sector_cfg["model_family"],
                                    f"artifacts/{run_id}/segments/{seg_key}/model.pkl",
                                    run_id,
                                    sector=sector,
                                    segment=split_value,
                                )
                            except Exception as seg_exc:
                                seg_status = "failed"
                                seg_error = str(seg_exc)
                                logger.warning(f"Segment {seg_key} failed: {seg_exc}")

                        with app_session() as s:
                            seg_row = CalibrationRunSegment(
                                calibration_run_id=CalibrationRun.query.filter_by(
                                    run_id=run_id
                                )
                                .first()
                                .id,
                                segment_key=seg_key,
                                sector=sector,
                                split_by=split_col,
                                split_value=split_value,
                                row_count=len(df_group),
                                ead_total=seg_ead,
                                artifact_path=seg_artifact_path,
                                train_metrics_json=json.dumps(seg_train_metrics)
                                if seg_train_metrics
                                else None,
                                val_metrics_json=json.dumps(seg_val_metrics)
                                if seg_val_metrics
                                else None,
                                status=seg_status,
                                error_message=seg_error,
                                model_config_id=sector_cfg["model_config_id"],
                            )
                            s.add(seg_row)

                    processed += 1
                    pct = 20 + int(processed / total_sectors * 75)
                    _write_progress(
                        run_id,
                        pct,
                        f"Trained sector '{sector}' ({processed}/{total_sectors})",
                        sector=sector,
                    )

                with app_session() as s:
                    r = CalibrationRun.query.filter_by(run_id=run_id).first()
                    r.status = "success"
                    r.finished_at = datetime.now(timezone.utc)
                    r.artifact_path = None  # segments table is the manifest
                    s.add(r)
                _write_progress(run_id, 100, "Segmented calibration completed")
                if initial_workflow_run_id:
                    advance_workflow.delay(initial_workflow_run_id)
                return

            # --- 3. Feature prep (single-model path) ---
            candidate_cols = feature_cols_json or [
                c for c in df.columns if c != target_col
            ]
            X_df = df[candidate_cols].select_dtypes(include=[np.number])
            # Update feature_cols to only the columns that actually went into X
            # (non-numeric columns are silently dropped by select_dtypes)
            feature_cols = list(X_df.columns)
            X = X_df.values
            y = df[target_col].values

            # Metadata = every column not actually used as a feature and not the target
            # This captures client_id, date, sector, country, and any merged identifier columns
            meta_col_set = set(feature_cols) | {target_col}
            meta_cols = [c for c in df.columns if c not in meta_col_set]
            df_val_meta = df[meta_cols]  # sliced to idx_val below after split

            # Split by index so metadata rows stay aligned with val predictions
            idx = np.arange(len(df))
            idx_train, idx_val = train_test_split(
                idx, test_size=round(1.0 - train_split_ratio, 4), random_state=42
            )
            X_train, X_val = X[idx_train], X[idx_val]
            y_train, y_val = y[idx_train], y[idx_val]
            df_val_meta = df_val_meta.iloc[idx_val].reset_index(drop=True)

            scaler = _get_scaler(scaler_name)
            if scaler:
                X_train = scaler.fit_transform(X_train)
                X_val = scaler.transform(X_val)
            _write_progress(run_id, 35, "Feature prep complete")

            # --- 4. Init model ---
            plugin_cls = get_model_class(algorithm)
            plugin = plugin_cls()

            # --- 4b. Optional CV hyperparameter search ---
            cv_summary = None
            if search_cfg and search_cfg.get("param_grid"):
                _write_progress(
                    run_id, 36, f"Starting {search_cfg.get('type', 'grid')} search…"
                )
                search_result = _cv_search(
                    plugin_cls, raw_params, search_cfg, X_train, y_train, run_id
                )
                raw_params = search_result["best_params"]
                cv_summary = search_result
                _write_progress(
                    run_id,
                    50,
                    f"CV search done · best score={search_result['best_score']:.4f}"
                    if search_result["best_score"] is not None
                    else "CV search done · no valid candidates found",
                )

            params_obj = plugin_cls.param_schema(**raw_params)

            # --- 5. Fit ---
            _write_progress(run_id, 50, f"Fitting {algorithm}…")
            plugin.fit(X_train, y_train, params_obj)
            _write_progress(run_id, 75, "Computing diagnostics…")

            # --- 6. Diagnostics ---
            diag = plugin.diagnostics(X_val, y_val)
            # Patch placeholder feature names (f0, f1…) with actual column names
            for key in ("feature_importance", "coef_table"):
                if key in diag and feature_cols:
                    for i, entry in enumerate(diag[key]):
                        if i < len(feature_cols):
                            entry["feature"] = feature_cols[i]

            y_train_pred = plugin.predict(X_train)
            y_val_pred = plugin.predict(X_val)
            try:
                if model_family == "classification":
                    train_metrics = {
                        "auc_roc": float(roc_auc_score(y_train, y_train_pred))
                    }
                else:
                    train_metrics = {
                        "r2": float(r2_score(y_train, y_train_pred)),
                        "rmse": float(
                            np.sqrt(mean_squared_error(y_train, y_train_pred))
                        ),
                    }
            except Exception:
                train_metrics = {}

            # --- 7. Save artifact ---
            artifact_bytes = pickle.dumps(
                {"model": plugin, "scaler": scaler, "feature_cols": feature_cols}
            )
            artifact_path = storage.upload_bytes(
                f"artifacts/{run_id}/model.pkl",
                artifact_bytes,
                "application/octet-stream",
            )

            # --- 8. Persist success ---
            # Build meta dict before opening the DB session (pandas still in scope)
            def _coerce(v):
                if v is None or isinstance(v, (str, bool)):
                    return v
                if isinstance(v, float):
                    return float(v)
                if isinstance(v, (int, np.integer)):
                    return int(v)
                return str(v)

            meta_dict = {
                col: [_coerce(v) for v in df_val_meta[col].tolist()]
                for col in meta_cols
            }
            actuals_list = [float(v) if v is not None else None for v in y_val.tolist()]
            predicted_list = [
                float(v) if v is not None else None for v in y_val_pred.tolist()
            ]
            client_ids_list = meta_dict.get("client_id", [None] * len(actuals_list))
            dates_list = meta_dict.get("date", [None] * len(actuals_list))
            other_keys = [k for k in meta_cols if k not in ("client_id", "date")]

            from project.db_models.calibration_models import ForecastResult

            with app_session() as s:
                r = CalibrationRun.query.filter_by(run_id=run_id).first()
                r.status = "success"
                r.finished_at = datetime.now(timezone.utc)
                r.artifact_path = artifact_path
                r.val_metrics_json = json.dumps(diag)
                r.train_metrics_json = json.dumps(train_metrics)
                if cv_summary:
                    r.best_params_json = json.dumps(cv_summary)
                s.add(r)

                frow = Forecast(
                    calibration_run_id=r.id,
                    forecast_horizon=len(y_val),
                )
                s.add(frow)
                s.flush()

                result_rows = [
                    {
                        "forecast_id": frow.id,
                        "actual": actuals_list[i],
                        "predicted": predicted_list[i],
                        "client_id": str(client_ids_list[i])
                        if client_ids_list[i] is not None
                        else None,
                        "date": str(dates_list[i])
                        if dates_list[i] is not None
                        else None,
                        "meta_json": json.dumps(
                            {k: meta_dict[k][i] for k in other_keys}
                        )
                        if other_keys
                        else None,
                    }
                    for i in range(len(actuals_list))
                ]
                s.bulk_insert_mappings(ForecastResult, result_rows)
            _write_progress(run_id, 100, "Run completed successfully")
            if initial_workflow_run_id:
                advance_workflow.delay(initial_workflow_run_id)

        except Exception as exc:
            logger.error(f"Calibration run {run_id} failed: {exc}", exc_info=True)
            with app_session() as s:
                r = CalibrationRun.query.filter_by(run_id=run_id).first()
                if r:
                    r.status = "failed"
                    r.finished_at = datetime.now(timezone.utc)
                    r.error_message = format_failure(exc)
                    s.add(r)
            _write_progress(run_id, Progress.FAILED, f"Failed: {exc}")
            if initial_workflow_run_id:
                advance_workflow.delay(initial_workflow_run_id)
            raise


@celery_app.task(bind=True, name="run_segment_calibration")
def run_segment_calibration(self, run_id: str, segment_key: str):
    """Re-fit one segment of an already-completed segmented calibration run,
    using its (possibly customized) hyperparams_json override. Only this
    segment's row is touched — the parent run and every other segment are
    left exactly as they are."""
    app = _make_flask_app()
    with app.app_context():
        from project import app_session
        from project.db_models.calibration_models import (
            CalibrationRun,
            CalibrationRunSegment,
            Dataset,
            ModelConfig,
        )

        # --- 0. Load run + segment, extract every scalar before any session-closing call ---
        run = CalibrationRun.query.filter_by(run_id=run_id).first()
        if not run:
            logger.error(f"CalibrationRun {run_id} not found")
            return
        seg = CalibrationRunSegment.query.filter_by(
            calibration_run_id=run.id, segment_key=segment_key
        ).first()
        if not seg:
            logger.error(f"Segment {segment_key} not found on run {run_id}")
            return

        dataset_id = run.dataset_id
        train_split_ratio = run.train_split if run.train_split is not None else 0.8
        scaler_name = run.scaler
        target_col = run.target_col or ""
        default_feature_cols = json.loads(run.feature_cols_json or "[]")
        # Per-segment feature override, if the customize panel set one; NULL falls
        # back to the run defaults.
        seg_feature_cols = json.loads(seg.feature_cols_json or "null")
        feature_cols = (
            seg_feature_cols if seg_feature_cols is not None else default_feature_cols
        )
        sector_overrides = json.loads(run.seg_sector_overrides_json or "{}")

        sector = seg.sector
        split_col = seg.split_by
        split_value = seg.split_value
        seg_id = seg.id
        override_hyperparams = json.loads(seg.hyperparams_json or "null")
        model_config_id = seg.model_config_id or run.model_config_id

        max_seg = (
            sector_overrides.get(sector, {}).get("max_segments") or run.seg_max_segments
        )

        cfg = ModelConfig.query.get(model_config_id)
        if not cfg:
            logger.error(
                f"ModelConfig {model_config_id} not found for segment {segment_key}"
            )
            return
        algorithm = cfg.algorithm
        model_family = cfg.family
        raw_params = override_hyperparams or json.loads(cfg.hyperparams_json or "{}")

        try:
            with app_session() as s:
                row = CalibrationRunSegment.query.get(seg_id)
                row.status = "running"
                row.error_message = None
                s.add(row)
            _cal_log(
                run_id,
                f"Re-fitting segment '{sector} · {split_value}' with {algorithm}…",
                sector=sector,
                segment=split_value,
            )

            ds = Dataset.query.get(dataset_id)
            if not ds.file_path:
                raise ValueError(
                    "No file path on dataset — live query results must be cached first"
                )

            file_bytes = storage.download_bytes(ds.file_path.split("/", 1)[-1])
            ext = ds.file_path.rsplit(".", 1)[-1].lower()
            buf = io.BytesIO(file_bytes)
            if ext == "csv":
                df = pd.read_csv(buf)
            elif ext == "xlsx":
                df = pd.read_excel(buf)
            elif ext == "parquet":
                df = pd.read_parquet(buf)
            else:
                raise ValueError(f"Unsupported file type: {ext}")

            if "sector" not in df.columns:
                raise ValueError(
                    "Dataset must contain a 'sector' column for segmented calibration"
                )

            df_sector = df[df["sector"] == sector]
            groups = _sector_split_groups(df_sector, split_col, max_seg)
            if groups is None or split_value not in groups:
                raise ValueError(
                    f"Could not reproduce segment group for '{segment_key}'"
                )
            df_group = groups[split_value]

            min_rows = 10
            if len(df_group) < min_rows:
                raise ValueError(f"Only {len(df_group)} rows (min {min_rows})")

            val_metrics, train_metrics, artifact_path = _fit_segment(
                df_group,
                algorithm,
                raw_params,
                None,  # no CV search on a single-segment re-run — hyperparams are explicit
                train_split_ratio,
                scaler_name,
                target_col,
                feature_cols,
                model_family,
                f"artifacts/{run_id}/segments/{segment_key}/model.pkl",
                run_id,
                sector=sector,
                segment=split_value,
            )

            with app_session() as s:
                row = CalibrationRunSegment.query.get(seg_id)
                row.status = "success"
                row.artifact_path = artifact_path
                row.train_metrics_json = json.dumps(train_metrics)
                row.val_metrics_json = json.dumps(val_metrics)
                row.error_message = None
                s.add(row)

            _cal_log(
                run_id,
                f"Segment '{sector} · {split_value}' re-fit complete",
                sector=sector,
                segment=split_value,
            )

            # Re-fitting this segment invalidated its downstream forecast + credit
            # results. Recompute them for THIS segment only (dispatch after the
            # commit above so the worker reads the fresh artifact + success status).
            recompute_segment_downstream.delay(run_id, segment_key)

        except Exception as exc:
            logger.error(
                f"Segment re-run {run_id}/{segment_key} failed: {exc}", exc_info=True
            )
            _cal_log(
                run_id,
                f"Segment '{sector} · {split_value}' re-fit failed: {exc}",
                level="error",
                sector=sector,
                segment=split_value,
            )
            with app_session() as s:
                row = CalibrationRunSegment.query.get(seg_id)
                if row:
                    row.status = "failed"
                    row.error_message = format_failure(exc)
                    s.add(row)
            raise


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
    return [
        {
            "forecast_run_id": fr_id,
            "date": str(dates_list[i]) if dates_list[i] is not None else None,
            "predicted": predicted_list[i],
            "meta_json": json.dumps({k: meta_dict[k][i] for k in other_keys})
            if other_keys
            else None,
            "segment_key": segment_key,
        }
        for i in range(len(predicted_list))
    ]


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


def _write_forecast_progress(
    run_id: str,
    progress: int,
    message: str,
    level: str = "info",
    sector: str | None = None,
    segment: str | None = None,
):
    """Write progress + a log line for a forecast run. Silent-fails so the task is never blocked.

    ``sector``/``segment`` tag a segment-scoped line for the unified workflow log."""
    try:
        from project.db_models.forecast_models import ForecastRun, ForecastRunLog

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        # worker_session() so this write never expires ORM objects the task holds.
        with worker_session() as s:
            r = s.query(ForecastRun).filter_by(run_id=run_id).first()
            if r:
                r.progress = max(0, progress)
            s.add(
                ForecastRunLog(
                    run_id=run_id,
                    t=now,
                    level=level,
                    message=message,
                    sector=sector,
                    segment=segment,
                )
            )
    except Exception:
        # Progress/log writes must never kill a run, but a silent failure hides
        # real DB problems — log it instead of swallowing outright.
        logger.exception("_write_forecast_progress failed for run %s", run_id)


@celery_app.task(bind=True, name="run_forecast")
def run_forecast(self, run_id: str):
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
                result_rows = [
                    {
                        "forecast_run_id": r.id,
                        "date": str(dates_list[i])
                        if dates_list[i] is not None
                        else None,
                        "predicted": predicted_list[i],
                        "meta_json": json.dumps(
                            {k: meta_dict[k][i] for k in other_keys}
                        )
                        if other_keys
                        else None,
                        "segment_key": seg_key_col[i] if seg_key_col else None,
                    }
                    for i in range(len(predicted_list))
                ]
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


def _cr_log(
    cr_run_id: str,
    message: str,
    level: str = "info",
    progress: int | None = None,
    sector: str | None = None,
    segment: str | None = None,
):
    """Write a log line for a credit risk run. Silent-fails so the task is never blocked.

    ``sector``/``segment`` tag a segment-scoped line for the unified workflow log."""
    try:
        from project.db_models.credit_models import CreditRiskRun, CreditRiskRunLog

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        # worker_session() so this write never expires ORM objects the task holds.
        with worker_session() as s:
            s.add(
                CreditRiskRunLog(
                    run_id=cr_run_id,
                    t=now,
                    level=level,
                    message=message,
                    sector=sector,
                    segment=segment,
                )
            )
            if progress is not None:
                r = s.query(CreditRiskRun).filter_by(run_id=cr_run_id).first()
                if r:
                    r.progress = progress
    except Exception as _e:
        logger.warning(f"_cr_log failed: {_e}")


def _compute_credit_for_clients(
    cr_run_id: str,
    clients_list: list,
    forecast_segmentation: dict,
    forecast_by_var: dict,
    pd_rating_df,
    exposure: float,
    discount_rate: float,
    lifetime_horizon: int,
    *,
    flush_every: int = 10,
    progress_base: int = 0,
    progress_span: int = 100,
) -> tuple[int, int]:
    """Run KMV + ECL for each client in `clients_list`, persisting a CreditRiskResult
    per client (with denormalised sector/subsector/country/segment_key so a single
    segment's rows can later be recomputed via an indexed WHERE). Returns
    (n_succeeded, n_failed).

    Shared by run_credit_analysis (whole portfolio) and recompute_segment_downstream
    (only the clients in one segment). `flush_every` batches the session commits; the
    per-segment recompute passes a large value so its small subset lands in one txn.
    Client→segment routing uses total_assets' seg_info as the canonical key source —
    the 3 required slots share one segmentation policy within a workflow submission.
    """
    from project import app_session
    from project.core.credit_risk.ecl import compute_ecl
    from project.core.credit_risk.forecast_lookup import (
        lookup_forecast,
        resolve_segment_key,
    )
    from project.core.credit_risk.kmv import run_kmv
    from project.db_models.credit_models import CreditRiskResult

    canonical_seg = forecast_segmentation.get("total_assets", {"split_by": {}})

    def _lookup(key: str, sector: str, subsector: str, country: str) -> dict:
        return lookup_forecast(
            forecast_segmentation[key],
            forecast_by_var[key],
            sector,
            subsector,
            country,
        )

    n_clients = len(clients_list)
    result_batch: list[CreditRiskResult] = []
    failed_clients = 0

    for idx, row in enumerate(clients_list):
        client_id = str(row["client_id"])
        com_info = {
            "E0": float(row["market_cap"]),
            "volE": float(row["vol_equity"]),
            "r": float(row["risk_free_rate"]),
            "rating": str(row["rating"]),
        }

        sector = str(row.get("sector") or "")
        subsector = str(row.get("subsector") or "")
        country = str(row.get("country") or "")
        # Canonical segment this client routes to — persisted for per-segment
        # recompute + Sector/Segment result filters. None for non-segmented runs.
        client_segment_key = (
            resolve_segment_key(canonical_seg, sector, subsector, country)
            if canonical_seg.get("split_by")
            else None
        )
        # Tags for this client's log lines (sector always known; segment only on
        # segmented runs).
        client_sector = sector or None
        client_segment = _split_segment_key(client_segment_key)[1]

        # Build forecast DataFrame from the 3 calibrated variable indices, routing
        # this client to its own segment's trajectory (segmented) or the single
        # portfolio-wide trajectory. Multi-scenario data is used directly; fall back
        # to a single "Baseline" when the data has no scenario dimension.
        ta_by_scen = _lookup("total_assets", sector, subsector, country)
        cl_by_scen = _lookup("short_term_debts", sector, subsector, country)
        nc_by_scen = _lookup("long_term_debts", sector, subsector, country)

        all_scens = sorted(set(ta_by_scen) & set(cl_by_scen) & set(nc_by_scen))
        if not all_scens:
            all_scens = ["Baseline"]
            ta_by_scen = {"Baseline": next(iter(ta_by_scen.values()), {})}
            cl_by_scen = {"Baseline": next(iter(cl_by_scen.values()), {})}
            nc_by_scen = {"Baseline": next(iter(nc_by_scen.values()), {})}

        rows_fc = []
        for scen in all_scens:
            ta_yr = ta_by_scen.get(scen, {})
            cl_yr = cl_by_scen.get(scen, {})
            nc_yr = nc_by_scen.get(scen, {})
            years = sorted(set(ta_yr) & set(cl_yr) & set(nc_yr))
            for yr in years:
                rows_fc.append(
                    {
                        "YEAR": yr,
                        "SCENARIO": scen,
                        "Total_Asset": ta_yr[yr],
                        "CL": cl_yr[yr],
                        "NonCL": nc_yr[yr],
                    }
                )

        if not rows_fc:
            failed_clients += 1
            _cr_log(
                cr_run_id,
                f"Client {client_id}: no overlapping forecast years across all 3 variables — skipping",
                level="warn",
                sector=client_sector,
                segment=client_segment,
            )
            continue
        forecast = pd.DataFrame(rows_fc)

        try:
            kmv_df = run_kmv(com_info, forecast, pd_rating_df)
            ecl_df = compute_ecl(kmv_df, exposure, discount_rate, lifetime_horizon)
            kmv_records = kmv_df.where(pd.notnull(kmv_df), None).to_dict(
                orient="records"
            )
            ecl_records = ecl_df.where(pd.notnull(ecl_df), None).to_dict(
                orient="records"
            )
            result_batch.append(
                CreditRiskResult(
                    run_id=cr_run_id,
                    client_id=client_id,
                    kmv_json=json.dumps(kmv_records),
                    ecl_json=json.dumps(ecl_records),
                    sector=sector or None,
                    subsector=subsector or None,
                    country=country or None,
                    segment_key=client_segment_key,
                )
            )
        except Exception as client_err:
            failed_clients += 1
            _cr_log(
                cr_run_id,
                f"Client {client_id} failed: {client_err}",
                level="warn",
                sector=client_sector,
                segment=client_segment,
            )

        # Flush batch and update progress every `flush_every` clients or at the end.
        if (idx + 1) % flush_every == 0 or idx == n_clients - 1:
            with app_session() as s:
                for res in result_batch:
                    s.add(res)
                result_batch = []
            progress = progress_base + round((idx + 1) / n_clients * progress_span)
            _cr_log(
                cr_run_id,
                f"Processed {idx + 1}/{n_clients} clients",
                progress=progress,
            )

    return n_clients - failed_clients, failed_clients


@celery_app.task(bind=True, name="run_credit_analysis")
def run_credit_analysis(self, cr_run_id: str):
    app = _make_flask_app()
    with app.app_context():
        from project import app_session
        from project.api.credit_risk.routes import _pd_rating_df
        from project.db_models.calibration_models import Dataset
        from project.db_models.credit_models import CreditRiskRun
        from project.db_models.forecast_models import ForecastRun

        cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
        if not cr:
            logger.error(f"CreditRiskRun {cr_run_id} not found")
            return
        if cr.status == "failed":
            # Cancelled while queued — a worker picked it up after the fact.
            return

        workflow_run_id = cr.workflow_run_id
        dataset_id = cr.dataset_id
        financial_portfolio_dataset_id = cr.financial_portfolio_dataset_id
        forecast_inputs = {
            inp.slot: inp.forecast_run_uuid for inp in cr.forecast_inputs_rel
        }
        exposure = cr.exposure
        discount_rate = cr.discount_rate
        lifetime_horizon = cr.lifetime_horizon
        curve = cr.curve

        try:
            # 1. Mark running
            with app_session() as s:
                r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                r.status = "running"
                r.started_at = datetime.now(timezone.utc)
                s.add(r)
            if workflow_run_id:
                advance_workflow.delay(workflow_run_id)
            _cr_log(cr_run_id, "Analysis started")

            # 2. Load credit dataset from MinIO
            def _load_df_from_dataset(ds_id: int) -> tuple[str, pd.DataFrame]:
                """Download a dataset by PK and return (name, DataFrame)."""
                ds = Dataset.query.get(ds_id)
                if not ds or not ds.file_path:
                    raise ValueError(f"Dataset {ds_id} not found or has no file")
                name = ds.name
                file_bytes = storage.download_bytes(ds.file_path.split("/", 1)[-1])
                ext = ds.file_path.rsplit(".", 1)[-1].lower()
                buf = io.BytesIO(file_bytes)
                if ext == "csv":
                    return name, pd.read_csv(buf)
                elif ext == "xlsx":
                    return name, pd.read_excel(buf)
                elif ext == "parquet":
                    return name, pd.read_parquet(buf)
                raise ValueError(f"Unsupported file type: {ext}")

            credit_ds_name, credit_df = _load_df_from_dataset(dataset_id)
            _cr_log(cr_run_id, f"Loading credit portfolio: {credit_ds_name}")
            required_credit = {
                "client_id",
                "market_cap",
                "vol_equity",
                "risk_free_rate",
                "rating",
            }
            missing_credit = required_credit - set(credit_df.columns)
            if missing_credit:
                raise ValueError(
                    f"Credit dataset missing required columns: {missing_credit}"
                )

            # Optionally load financial portfolio and merge to get country/sector/subsector
            if financial_portfolio_dataset_id:
                fin_ds_name, fin_df = _load_df_from_dataset(
                    financial_portfolio_dataset_id
                )
                _cr_log(cr_run_id, f"Loading financial portfolio: {fin_ds_name}")
                required_fin = {"client_id", "country", "sector", "subsector"}
                missing_fin = required_fin - set(fin_df.columns)
                if missing_fin:
                    raise ValueError(
                        f"Financial portfolio dataset missing required columns: {missing_fin}"
                    )
                # One row per client for the metadata join (country/sector/subsector are static)
                fin_meta = fin_df[
                    ["client_id", "country", "sector", "subsector"]
                ].drop_duplicates(subset=["client_id"])
                # Only add columns from financial portfolio not already in credit portfolio
                new_fin_cols = ["client_id"] + [
                    c
                    for c in fin_meta.columns
                    if c != "client_id" and c not in credit_df.columns
                ]
                portfolio_df = credit_df.merge(
                    fin_meta[new_fin_cols], on="client_id", how="left"
                )
                _cr_log(
                    cr_run_id,
                    f"Merged {len(fin_meta)} financial portfolio clients into credit portfolio",
                    progress=2,
                )
            else:
                portfolio_df = credit_df

            n_clients = len(portfolio_df)
            _cr_log(cr_run_id, f"Loaded {n_clients} clients from dataset", progress=2)

            # 3. Build per-variable forecast indices from the 3 required forecast runs.
            #    idx_map[ctx][scenario][year] = predicted, where ctx is:
            #      - a segment_key (calibration was segmented — the forecast run scored
            #        every trained segment against the MEV-only dataset)
            #      - None (single portfolio-wide trajectory, non-segmented calibration)
            from project.core.credit_risk.forecast_lookup import (
                build_variable_index,
            )

            REQUIRED_INPUTS = ("total_assets", "short_term_debts", "long_term_debts")
            missing_inputs = [k for k in REQUIRED_INPUTS if not forecast_inputs.get(k)]
            if missing_inputs:
                raise ValueError(f"Missing required forecast inputs: {missing_inputs}")

            forecast_by_var: dict[
                str, dict[str | None, dict[str, dict[int, float]]]
            ] = {}
            # forecast_segmentation[key] = {
            #   "split_by": {sector: 'subsector'|'country'},
            #   "top_values": {sector: {trained split_value, ...}},  # includes "Others"
            #   "fallback": {sector: any segment_key for that sector},
            # }
            forecast_segmentation: dict[str, dict] = {}

            for key in REQUIRED_INPUTS:
                fr_run_uuid = forecast_inputs[key]
                fr = ForecastRun.query.filter_by(run_id=fr_run_uuid).first()
                if not fr or fr.status != "success":
                    raise ValueError(
                        f"Forecast run for '{key}' ({fr_run_uuid[:8]}…) not found or not successful"
                    )
                seg_info, idx_map = build_variable_index(fr)
                forecast_segmentation[key] = seg_info
                forecast_by_var[key] = idx_map

                ctx_desc = (
                    f"{len(idx_map)} segments"
                    if seg_info["split_by"]
                    else "portfolio-wide"
                )
                _cr_log(
                    cr_run_id,
                    f"Loaded '{key}' forecast from run {fr_run_uuid[:8]}… ({ctx_desc})",
                )

            # 4. Load PD ratings
            pd_rating_df = _pd_rating_df(curve)
            if pd_rating_df.empty:
                raise ValueError("No PD ratings found — run flask db upgrade first")
            _cr_log(
                cr_run_id,
                f"Loaded PD rating table ({len(pd_rating_df)} rows, curve={curve})",
                progress=5,
            )

            # 5. Process each client (KMV + ECL) and persist results.
            clients_list = portfolio_df.to_dict(orient="records")
            n_clients = len(clients_list)
            succeeded, failed_clients = _compute_credit_for_clients(
                cr_run_id,
                clients_list,
                forecast_segmentation,
                forecast_by_var,
                pd_rating_df,
                exposure,
                discount_rate,
                lifetime_horizon,
            )

            # 6. Mark success
            summary = f"Completed: {succeeded}/{n_clients} clients succeeded"
            if failed_clients:
                summary += f" ({failed_clients} failed)"
            _cr_log(cr_run_id, summary, progress=100)
            with app_session() as s:
                r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                r.status = "success"
                r.finished_at = datetime.now(timezone.utc)
                r.progress = 100
                s.add(r)

            # Results changed (initial run or rerun reusing this run_id) — drop the
            # cached results frame and transition matrices so reads recompute fresh.
            try:
                from project import cache

                cache.delete(f"cr_run_results:{cr_run_id}")
                cache.delete(f"cr_transitions:{cr_run_id}")
            except Exception:
                # Stale cache is self-healing (next read recomputes); log so a
                # persistently broken cache backend is still visible.
                logger.exception(
                    "Cache invalidation failed for credit run %s", cr_run_id
                )

            # 7. Materialise the Heatmap / Financial Forecast level series so those
            # pages load from cheap indexed SELECTs instead of recomputing from
            # MinIO + pandas on every request. Best-effort: a failure here must not
            # fail the analysis run (the pages fall back to lazy on-demand compute).
            try:
                from project.api.credit_risk.routes import (
                    _analysis_portfolio_df,
                    _slot_forecast_runs,
                )
                from project.core.credit_risk.analysis_series import (
                    materialize_analysis_series,
                )

                with app_session():
                    cr_obj = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                    portfolio_df = _analysis_portfolio_df(cr_obj)
                    slots = _slot_forecast_runs(cr_obj)
                    n_series = materialize_analysis_series(cr_obj, portfolio_df, slots)
                _cr_log(cr_run_id, f"Materialised {n_series} analysis series rows")
            except Exception as mat_err:
                logger.error(
                    f"Analysis-series materialisation failed for {cr_run_id}: {mat_err}",
                    exc_info=True,
                )
                _cr_log(
                    cr_run_id,
                    f"Analysis series not materialised: {mat_err}",
                    level="warn",
                )

            if workflow_run_id:
                advance_workflow.delay(workflow_run_id)

        except Exception as exc:
            logger.error(f"Credit risk run {cr_run_id} failed: {exc}", exc_info=True)
            _cr_log(cr_run_id, f"Analysis failed: {exc}", level="error")
            with app_session() as s:
                r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                if r:
                    r.status = "failed"
                    r.finished_at = datetime.now(timezone.utc)
                    r.error_message = format_failure(exc)
                    s.add(r)
            if workflow_run_id:
                advance_workflow.delay(workflow_run_id)
            raise


@celery_app.task(name="backfill_analysis_series")
def backfill_analysis_series(cr_run_id: str):
    """Materialise the Heatmap / Financial Forecast level series for a run that has
    none yet (a legacy run predating the feature, or one whose best-effort step at
    job completion failed).

    Dispatched from the analysis endpoints instead of computing inline in the web
    request — the portfolio load + per-client aggregation is a heavy pandas job that
    must never block an HTTP worker (or a 5s poll). Idempotent: rewrites the run's
    rows. The caller dedups dispatch with a short cache lock so concurrent pollers
    only enqueue this once.
    """
    from project import app_session
    from project.api.credit_risk.routes import (
        _analysis_portfolio_df,
        _slot_forecast_runs,
    )
    from project.core.credit_risk.analysis_series import materialize_analysis_series
    from project.db_models.credit_models import CreditRiskRun

    try:
        with app_session():
            cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
            if not cr or cr.status != "success":
                return
            portfolio_df = _analysis_portfolio_df(cr)
            slots = _slot_forecast_runs(cr)
            n_series = materialize_analysis_series(cr, portfolio_df, slots)
        _cr_log(cr_run_id, f"Backfilled {n_series} analysis series rows")
    except Exception as exc:
        logger.error(
            f"Analysis-series backfill failed for {cr_run_id}: {exc}", exc_info=True
        )
        _cr_log(cr_run_id, f"Analysis series backfill failed: {exc}", level="warn")
        raise


def _load_df_by_dataset_id(ds_id: int) -> "pd.DataFrame":
    """Download a dataset by PK and return its DataFrame (csv/xlsx/parquet)."""
    return dataset_io.load_dataset_df_by_id(ds_id)


def _build_credit_portfolio_df(
    credit_dataset_id: int, financial_dataset_id: int | None
) -> "pd.DataFrame":
    """Rebuild the same credit+financial merged portfolio the full credit run uses
    (mirrors run_credit_analysis' load/merge), so per-segment recompute routes
    clients identically."""
    credit_df = _load_df_by_dataset_id(credit_dataset_id)
    if not financial_dataset_id:
        return credit_df
    fin_df = _load_df_by_dataset_id(financial_dataset_id)
    fin_meta = fin_df[["client_id", "country", "sector", "subsector"]].drop_duplicates(
        subset=["client_id"]
    )
    new_fin_cols = ["client_id"] + [
        c for c in fin_meta.columns if c != "client_id" and c not in credit_df.columns
    ]
    return credit_df.merge(fin_meta[new_fin_cols], on="client_id", how="left")


@celery_app.task(bind=True, name="recompute_segment_downstream")
def recompute_segment_downstream(self, run_id: str, segment_key: str):
    """After a single segment is re-fit, recompute its downstream forecast + credit
    results IN PLACE — for that segment only — so the workflow's Forecast and Credit
    tabs stop showing numbers produced by the old segment model.

    Never calls advance_workflow: that machine is one-shot and would spawn duplicate
    runs. This is an out-of-band correction that flips the affected ForecastRun(s) +
    CreditRiskRun to running while recomputing, then back to success. Each per-segment
    delete+insert is one atomic transaction, gated behind status='running', so the
    frontend never renders a success run missing a segment's rows.
    """
    app = _make_flask_app()
    with app.app_context():
        from project import app_session
        from project.api.credit_risk.routes import _pd_rating_df
        from project.core.credit_risk.forecast_lookup import build_variable_index
        from project.db_models.calibration_models import (
            CalibrationRun,
            CalibrationRunSegment,
        )
        from project.db_models.credit_models import CreditRiskResult, CreditRiskRun
        from project.db_models.forecast_models import ForecastRun, ForecastRunLog

        # Sector/segment tags for the unified workflow log lines below.
        seg_sector, seg_split = _split_segment_key(segment_key)

        cal = CalibrationRun.query.filter_by(run_id=run_id).first()
        if not cal:
            logger.error(f"recompute_segment_downstream: cal run {run_id} not found")
            return
        if cal.seg_sectors_json is None:
            # Non-segmented run has no per-segment downstream to recompute.
            return
        cal_id = cal.id
        workflow_run_id = cal.workflow_run_id
        target_col = cal.target_col

        # Affected forecast runs: every forecast run built from this calibration.
        # (Segmented cals produce one forecast run per target, each scoring all
        # segments; a failed/incomplete run is left alone.)
        affected = ForecastRun.query.filter_by(
            calibration_run_id=cal_id, status="success"
        ).all()
        if not affected:
            return

        seg = CalibrationRunSegment.query.filter_by(
            calibration_run_id=cal_id, segment_key=segment_key, status="success"
        ).first()
        if not seg:
            logger.error(
                f"recompute_segment_downstream: segment '{segment_key}' not found/"
                f"successful for run {run_id}"
            )
            return
        seg_artifact_path = seg.artifact_path
        affected_ids = [(fr.id, fr.run_id, fr.dataset_id) for fr in affected]

        # ── Forecast stage: re-score this segment into each affected run ──────────
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        for fr_id, fr_run_uuid, fr_dataset_id in affected_ids:
            # Txn 1: gate the tab OFF before any delete.
            with app_session() as s:
                fr = ForecastRun.query.get(fr_id)
                fr.status = "running"
                fr.progress = 0
                s.add(fr)
                s.add(
                    ForecastRunLog(
                        run_id=fr_run_uuid,
                        t=now,
                        level="info",
                        message=f"Recomputing segment '{segment_key}'…",
                        sector=seg_sector,
                        segment=seg_split,
                    )
                )
            try:
                df = _load_df_by_dataset_id(fr_dataset_id)
                # Txn 2: atomic delete-this-segment + re-score + insert.
                with app_session() as s:
                    fr = ForecastRun.query.get(fr_id)
                    recompute_forecast_run_segment(
                        s, fr, df, seg_artifact_path, segment_key
                    )
                # Txn 3: back to success.
                with app_session() as s:
                    fr = ForecastRun.query.get(fr_id)
                    fr.status = "success"
                    fr.progress = 100
                    fr.finished_at = datetime.now(timezone.utc)
                    s.add(fr)
            except Exception as exc:
                logger.error(
                    f"Segment forecast recompute failed for {fr_run_uuid}: {exc}",
                    exc_info=True,
                )
                with app_session() as s:
                    fr = ForecastRun.query.get(fr_id)
                    fr.status = "failed"
                    fr.finished_at = datetime.now(timezone.utc)
                    fr.error_message = (
                        f"Segment '{segment_key}' recompute failed:\n"
                        f"{format_failure(exc)}"
                    )
                    s.add(fr)
                    s.add(
                        ForecastRunLog(
                            run_id=fr_run_uuid,
                            t=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                            level="error",
                            message=f"Segment '{segment_key}' recompute failed: {exc}",
                            sector=seg_sector,
                            segment=seg_split,
                        )
                    )
                # Credit needs all forecast inputs current — abort before it.
                raise

        # The re-scored forecast(s) feed the Heatmap / Financial Forecast level
        # series and the cached forecast index. Invalidate that index cache and, if
        # this workflow has a credit run, re-materialise the series so those pages
        # reflect the re-fit segment instead of stale pre-retrain numbers. Done here
        # (after the forecast stage, before the credit early-returns) because the
        # forecast change alone can move the Heatmap even when credit is unaffected.
        try:
            from project import cache

            for _, fr_run_uuid, _ in affected_ids:
                cache.delete(f"cr_var_index:{fr_run_uuid}")
            if workflow_run_id:
                cr_for_series = CreditRiskRun.query.filter_by(
                    workflow_run_id=workflow_run_id
                ).first()
                if cr_for_series and cr_for_series.status == "success":
                    backfill_analysis_series.delay(cr_for_series.run_id)
        except Exception:
            logger.warning(
                "post-recompute analysis-series refresh dispatch failed", exc_info=True
            )

        # ── Credit stage: recompute only this segment's clients ──────────────────
        # Only when the retrained variable actually feeds KMV (revenue/cogs don't).
        if SLOT_BY_TARGET.get(target_col) not in REQUIRED_SLOTS:
            return
        if not workflow_run_id:
            return
        cr = CreditRiskRun.query.filter_by(workflow_run_id=workflow_run_id).first()
        if not cr or cr.status != "success":
            return

        cr_run_id = cr.run_id
        cr_dataset_id = cr.dataset_id
        cr_financial_id = cr.financial_portfolio_dataset_id
        exposure = cr.exposure
        discount_rate = cr.discount_rate
        lifetime_horizon = cr.lifetime_horizon
        curve = cr.curve
        forecast_inputs = {
            inp.slot: inp.forecast_run_uuid for inp in cr.forecast_inputs_rel
        }

        # Membership is stable (re-fitting a model doesn't change routing), so read
        # the affected clients straight off the persisted segment_key column.
        client_ids = {
            r.client_id
            for r in CreditRiskResult.query.filter_by(
                run_id=cr_run_id, segment_key=segment_key
            ).all()
        }
        if not client_ids:
            # Nothing routes to this segment (or rows predate the column) — don't
            # flip a good run to running to do nothing.
            _cr_log(
                cr_run_id,
                f"Segment '{segment_key}' recompute: no matching credit clients — skipped",
                sector=seg_sector,
                segment=seg_split,
            )
            return

        # Txn A: gate credit tabs OFF.
        with app_session() as s:
            r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
            r.status = "running"
            r.progress = 0
            r.started_at = datetime.now(timezone.utc)
            s.add(r)
        _cr_log(
            cr_run_id,
            f"Recomputing credit for segment '{segment_key}' ({len(client_ids)} clients)…",
            sector=seg_sector,
            segment=seg_split,
        )

        try:
            # Rebuild forecast indices from the (now-updated) required forecast runs.
            REQUIRED_INPUTS = ("total_assets", "short_term_debts", "long_term_debts")
            missing_inputs = [k for k in REQUIRED_INPUTS if not forecast_inputs.get(k)]
            if missing_inputs:
                raise ValueError(f"Missing required forecast inputs: {missing_inputs}")
            forecast_by_var: dict = {}
            forecast_segmentation: dict = {}
            for key in REQUIRED_INPUTS:
                fr = ForecastRun.query.filter_by(run_id=forecast_inputs[key]).first()
                if not fr or fr.status != "success":
                    raise ValueError(
                        f"Forecast run for '{key}' not found or not successful"
                    )
                seg_info, idx_map = build_variable_index(fr)
                forecast_segmentation[key] = seg_info
                forecast_by_var[key] = idx_map

            pd_rating_df = _pd_rating_df(curve)
            if pd_rating_df.empty:
                raise ValueError("No PD ratings found — run flask db upgrade first")

            portfolio_df = _build_credit_portfolio_df(cr_dataset_id, cr_financial_id)
            subset_df = portfolio_df[
                portfolio_df["client_id"].astype(str).isin(client_ids)
            ]

            # Txn B: atomic delete-this-segment + recompute (one flush for the subset).
            with app_session() as s:
                CreditRiskResult.query.filter_by(
                    run_id=cr_run_id, segment_key=segment_key
                ).delete(synchronize_session=False)
            _compute_credit_for_clients(
                cr_run_id,
                subset_df.to_dict(orient="records"),
                forecast_segmentation,
                forecast_by_var,
                pd_rating_df,
                exposure,
                discount_rate,
                lifetime_horizon,
                flush_every=max(1, len(subset_df)),
            )

            # Txn C: back to success + invalidate the cached results df.
            with app_session() as s:
                r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                r.status = "success"
                r.progress = 100
                r.finished_at = datetime.now(timezone.utc)
                s.add(r)
            try:
                from project import cache

                cache.delete(f"cr_run_results:{cr_run_id}")
                cache.delete(f"cr_transitions:{cr_run_id}")
            except Exception:
                # Stale cache is self-healing (next read recomputes); log so a
                # persistently broken cache backend is still visible.
                logger.exception(
                    "Cache invalidation failed for credit run %s", cr_run_id
                )
            _cr_log(
                cr_run_id,
                f"Segment '{segment_key}' credit recompute complete",
                progress=100,
                sector=seg_sector,
                segment=seg_split,
            )
        except Exception as exc:
            logger.error(
                f"Segment credit recompute failed for {cr_run_id}: {exc}",
                exc_info=True,
            )
            _cr_log(
                cr_run_id,
                f"Segment recompute failed: {exc}",
                level="error",
                sector=seg_sector,
                segment=seg_split,
            )
            with app_session() as s:
                r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                if r:
                    r.status = "failed"
                    r.finished_at = datetime.now(timezone.utc)
                    r.error_message = (
                        f"Segment '{segment_key}' recompute failed:\n"
                        f"{format_failure(exc)}"
                    )
                    s.add(r)
            raise


# Maps a workflow target_col to the slot name CreditRiskForecastInput/
# run_credit_analysis expects — the two use different vocabularies for the
# same three variables.
SLOT_BY_TARGET = {
    "total_assets": "total_assets",
    "total_shortterm_debts": "short_term_debts",
    "total_longterm_debts": "long_term_debts",
    "total_revenue": "total_revenue",
    "total_cogs": "total_cogs",
}
# These slots must be present for credit analysis to run; revenue/cogs are optional
# (they enable heatmap metrics but the KMV/ECL computation doesn't require them).
REQUIRED_SLOTS = {"total_assets", "short_term_debts", "long_term_debts"}


def advance_workflow_impl(workflow_run_id: int):
    """Check a workflow's children and advance it to its next stage, or
    finalize it as failed/success. Called after every status transition
    (running/success/failed) on a workflow's calibration/forecast/credit-risk
    children.

    DB-driven completion-check pattern rather than a Celery chain/chord: each
    child task already owns its own status transitions, so this just re-reads
    the workflow's children on every call and decides what (if anything) the
    workflow should do next. The workflow row is locked for the duration of
    the check via SELECT ... FOR UPDATE (a no-op hint on SQLite, used in
    tests), and `current_stage` acts as a guard — two children finishing at
    the same instant both call this, but the second call sees the stage the
    first one already advanced to and does nothing.
    """
    from project import app_session
    from project.db_models.calibration_models import CalibrationRun
    from project.db_models.credit_models import CreditRiskForecastInput, CreditRiskRun
    from project.db_models.forecast_models import ForecastRun
    from project.db_models.workflow_models import WorkflowRun

    to_dispatch: list[tuple[str, str]] = []

    with app_session() as s:
        wf = WorkflowRun.query.filter_by(id=workflow_run_id).with_for_update().first()
        if not wf or wf.status in ("success", "failed"):
            return  # terminal or missing — idempotent no-op

        cals = CalibrationRun.query.filter_by(workflow_run_id=wf.id).all()
        fcs = ForecastRun.query.filter_by(workflow_run_id=wf.id).all()
        crs = CreditRiskRun.query.filter_by(workflow_run_id=wf.id).all()

        def _first_failed(runs, stage_label):
            for r in runs:
                if r.status == "failed":
                    label = getattr(r, "target_col", None) or r.run_id
                    return stage_label, label, r.error_message
            return None

        failed = (
            _first_failed(cals, "Training")
            or _first_failed(fcs, "Forecast")
            or _first_failed(crs, "Credit analysis")
        )
        if failed:
            stage_label, label, err = failed
            wf.status = "failed"
            wf.finished_at = datetime.now(timezone.utc)
            wf.error_message = (
                f"{stage_label} failed for '{label}': {err or 'unknown error'}"
            )
            s.add(wf)
            return

        if wf.status == "queued":
            # Reaching this point means the workflow isn't failed/finished, so
            # some child has moved past "queued" — reflect that even if the
            # triggering child raced ahead to "success" before we got here.
            wf.status = "running"
            wf.started_at = wf.started_at or datetime.now(timezone.utc)
            s.add(wf)

        if (
            wf.current_stage == "training"
            and cals
            and all(c.status == "success" for c in cals)
        ):
            for cal in cals:
                fr = ForecastRun(
                    run_id=str(uuid.uuid4()),
                    name=f"{wf.name} · {cal.target_col}",
                    calibration_run_id=cal.id,
                    dataset_id=wf.forecast_dataset_id,
                    status="queued",
                    triggered_by=wf.triggered_by,
                    created_at=datetime.now(timezone.utc),
                    workflow_run_id=wf.id,
                )
                s.add(fr)
                s.flush()
                to_dispatch.append(("run_forecast", fr.run_id))
            wf.current_stage = "forecast"
            s.add(wf)

        elif (
            wf.current_stage == "forecast"
            and fcs
            and all(f.status == "success" for f in fcs)
        ):
            target_by_cal_id = {c.id: c.target_col for c in cals}
            slots: dict[str, ForecastRun] = {}
            for fr in fcs:
                slot = SLOT_BY_TARGET.get(target_by_cal_id.get(fr.calibration_run_id))
                if slot:
                    slots[slot] = fr
            required_slots = REQUIRED_SLOTS
            missing_slots = required_slots - set(slots.keys())

            if missing_slots or not wf.credit_dataset_id:
                if missing_slots:
                    missing_targets = [
                        t for t, sl in SLOT_BY_TARGET.items() if sl in missing_slots
                    ]
                    reason = (
                        "Credit analysis skipped — training did not include all "
                        f"required targets: {', '.join(missing_targets)}"
                    )
                else:
                    reason = (
                        "Credit analysis skipped — no credit portfolio dataset "
                        "available"
                    )
                wf.current_stage = "done"
                wf.status = "success"
                wf.finished_at = datetime.now(timezone.utc)
                wf.analysis_skipped_reason = reason
                s.add(wf)
            else:
                params = json.loads(wf.analysis_params_json or "{}")
                cr = CreditRiskRun(
                    run_id=str(uuid.uuid4()),
                    dataset_id=wf.credit_dataset_id,
                    financial_portfolio_dataset_id=wf.financial_dataset_id,
                    is_active=False,
                    exposure=float(params.get("exposure", 1_000_000)),
                    discount_rate=float(params.get("discount_rate", 0.05)),
                    lifetime_horizon=int(params.get("lifetime_horizon", 5)),
                    curve=params.get("curve", "moodys"),
                    status="queued",
                    triggered_by=wf.triggered_by,
                    created_at=datetime.now(timezone.utc),
                    workflow_run_id=wf.id,
                )
                s.add(cr)
                s.flush()
                for slot, fr in slots.items():
                    s.add(
                        CreditRiskForecastInput(
                            credit_risk_run_id=cr.id,
                            forecast_run_id=fr.id,
                            forecast_run_uuid=fr.run_id,
                            slot=slot,
                        )
                    )
                wf.current_stage = "analysis"
                s.add(wf)
                s.flush()
                to_dispatch.append(("run_credit_analysis", cr.run_id))

        elif (
            wf.current_stage == "analysis"
            and crs
            and all(c.status == "success" for c in crs)
        ):
            wf.current_stage = "done"
            wf.status = "success"
            wf.finished_at = datetime.now(timezone.utc)
            s.add(wf)

    # Dispatch only after the transaction above has committed — otherwise a
    # worker could pick up the new run before its row is visible.
    for task_name, rid in to_dispatch:
        (run_forecast if task_name == "run_forecast" else run_credit_analysis).delay(
            rid
        )


@celery_app.task(bind=True, name="advance_workflow")
def advance_workflow(self, workflow_run_id: int):
    app = _make_flask_app()
    with app.app_context():
        advance_workflow_impl(workflow_run_id)


@celery_app.task(bind=True, name="delete_workflow")
def delete_workflow(self, run_id: str):
    """Purge a workflow and all its runs in the background. The API route has
    already validated the delete is safe and flipped the workflow to the
    ``deleting`` status; this does the heavy set-based deletion + MinIO cleanup.

    On any unexpected error the workflow is reverted out of ``deleting`` to a
    ``failed`` status with the traceback, so a row can never get stuck showing
    "Deleting…" forever.
    """
    from project import app_session
    from project.core.workflow_delete import purge_workflow
    from project.db_models.workflow_models import WorkflowRun

    app = _make_flask_app()
    with app.app_context():
        wf = WorkflowRun.query.filter_by(run_id=run_id).first()
        if not wf:
            return  # already gone — idempotent no-op
        wf_id = wf.id
        try:
            purge_workflow(wf_id)
        except Exception as e:  # noqa: BLE001 - surface, never leave stuck
            logger.exception("Workflow %s deletion failed", run_id)
            with app_session() as s:
                wf = WorkflowRun.query.filter_by(id=wf_id).first()
                if wf:
                    wf.status = "failed"
                    wf.error_message = f"Deletion failed:\n{format_failure(e)}"
                    wf.finished_at = datetime.now(timezone.utc)
                    s.add(wf)
            raise
