import io
import itertools
import json
import pickle
import random
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

from project.constants import Progress
from project.core import storage
from project.core.model_registry import get_model_class
from project.workers import celery_app
from project.workers.common import (
    _cal_log,
    _get_scaler,
    _make_flask_app,
    _write_progress,
    format_failure,
)


from project.logger import get_logger

logger = get_logger(__name__)


def _val_test_size(train_split_ratio: float) -> float:
    """Validation fraction for train_test_split, guaranteed to be a valid
    sklearn ``test_size`` (a float in the open interval (0, 1)).

    New configs are bounded to 0.5–0.95 at the API, but legacy rows may carry
    train_split == 1.0, which would yield test_size 0.0 and raise
    ``InvalidParameterError``. Clamp so a validation holdout always exists."""
    return float(np.clip(round(1.0 - train_split_ratio, 4), 0.05, 0.95))


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
        idx, test_size=_val_test_size(train_split_ratio), random_state=42
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
    from project.workers.workflow import (
        advance_workflow,
    )  # deferred: avoids task-dispatch import cycle

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
                idx, test_size=_val_test_size(train_split_ratio), random_state=42
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
    from project.workers.segments import (
        recompute_segment_downstream,
    )  # deferred: avoids import cycle

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
