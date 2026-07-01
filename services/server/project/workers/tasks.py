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
from sklearn.preprocessing import MinMaxScaler, RobustScaler, StandardScaler

from project.core import storage
from project.core.model_registry import get_model_class
from project.logger import get_logger
from project.workers import celery_app


def _load_forecast_data(forecast) -> dict:
    """Load forecast payload — forecast_results rows for new runs, forecast_json fallback for old."""
    from project.db_models.calibration_models import ForecastResult

    if forecast.results.count() > 0:
        rows = forecast.results.order_by(ForecastResult.id).all()
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


def _write_progress(run_id: str, progress: int, message: str):
    """Write progress + a log line to DB. Always silent-fails so calibration is never blocked."""
    try:
        from project import app_session
        from project.db_models.calibration_models import (
            CalibrationRun,
            CalibrationRunLog,
        )

        level = (
            "error"
            if progress < 0
            else ("warn" if "warn" in message.lower() else "info")
        )
        with app_session() as s:
            r = CalibrationRun.query.filter_by(run_id=run_id).first()
            if r:
                r.progress = max(0, progress)
                r.progress_message = message
                s.add(r)
            s.add(
                CalibrationRunLog(
                    run_id=run_id,
                    logged_at=datetime.now(timezone.utc),
                    level=level,
                    message=message,
                )
            )
    except Exception:
        pass


def _cv_search(
    plugin_cls, base_params: dict, search_cfg: dict, X_train, y_train, run_id: str
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
) -> tuple[dict, dict, str]:
    """Fit one model on df_group, save artifact to MinIO, return (val_metrics, train_metrics, artifact_path)."""
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
            plugin_cls, raw_params, search_cfg, X_train, y_train, run_id
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

                    if split_col not in df_sector.columns:
                        logger.warning(
                            f"Sector '{sector}': split column '{split_col}' not found, skipping"
                        )
                        continue

                    # Rank groups by EAD descending; fall back to row count if no ead col
                    if "ead" in df_sector.columns:
                        ead_ranks = (
                            df_sector.groupby(split_col)["ead"]
                            .sum()
                            .sort_values(ascending=False)
                        )
                    else:
                        ead_ranks = (
                            df_sector.groupby(split_col)
                            .size()
                            .sort_values(ascending=False)
                        )

                    top_values = list(ead_ranks.index[:max_seg])
                    rest_values = list(ead_ranks.index[max_seg:])

                    groups: dict[str, pd.DataFrame] = {
                        v: df_sector[df_sector[split_col] == v] for v in top_values
                    }
                    if rest_values:
                        groups["Others"] = df_sector[
                            df_sector[split_col].isin(rest_values)
                        ]

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
                    )

                with app_session() as s:
                    r = CalibrationRun.query.filter_by(run_id=run_id).first()
                    r.status = "success"
                    r.finished_at = datetime.now(timezone.utc)
                    r.artifact_path = None  # segments table is the manifest
                    s.add(r)
                _write_progress(run_id, 100, "Segmented calibration completed")
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

        except Exception as exc:
            logger.error(f"Calibration run {run_id} failed: {exc}", exc_info=True)
            with app_session() as s:
                r = CalibrationRun.query.filter_by(run_id=run_id).first()
                if r:
                    r.status = "failed"
                    r.finished_at = datetime.now(timezone.utc)
                    r.error_message = str(exc)
                    s.add(r)
            _write_progress(run_id, -1, f"Failed: {exc}")
            raise


def _write_forecast_progress(
    run_id: str, progress: int, message: str, level: str = "info"
):
    """Write progress + a log line for a forecast run. Silent-fails so the task is never blocked."""
    try:
        from project import app_session
        from project.db_models.forecast_models import ForecastRun, ForecastRunLog

        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        with app_session() as s:
            r = ForecastRun.query.filter_by(run_id=run_id).first()
            if r:
                r.progress = max(0, progress)
                s.add(r)
            s.add(ForecastRunLog(run_id=run_id, t=now, level=level, message=message))
    except Exception:
        pass


@celery_app.task(bind=True, name="run_forecast")
def run_forecast(self, run_id: str):
    app = _make_flask_app()
    with app.app_context():
        import pickle

        from project import app_session
        from project.db_models.calibration_models import CalibrationRun, Dataset
        from project.db_models.forecast_models import ForecastRun, ForecastRunResult

        # Load all needed DB values as plain scalars before any session closes.
        with app_session() as s:
            fr = ForecastRun.query.filter_by(run_id=run_id).first()
            if not fr:
                logger.error(f"ForecastRun {run_id} not found")
                return
            cal_run = CalibrationRun.query.get(fr.calibration_run_id)
            ds = Dataset.query.get(fr.dataset_id)
            if not cal_run:
                raise ValueError("Calibration run not found")
            if not ds or not ds.file_path:
                raise ValueError(f"Dataset {fr.dataset_id} not found or has no file")
            cal_run_id_int = cal_run.id
            artifact_path = cal_run.artifact_path
            is_segmented = cal_run.seg_sectors_json is not None
            segment_key = fr.segment_key
            ds_file_path = ds.file_path
            fr.status = "running"
            fr.started_at = datetime.now(timezone.utc)
            s.add(fr)

        try:
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
                """Score one segment's model against every row of df.

                Returns (predicted_list, meta_rows) where meta_rows are per-row dicts
                of non-feature columns, each tagged with segment_key so credit risk
                analysis can later route each client to the matching segment.
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

                predicted = [
                    float(v) if v is not None else None for v in preds.tolist()
                ]
                return predicted, meta_rows

            if segment_key:
                # Score one named segment against the whole forecast dataset.
                from project.db_models.calibration_models import CalibrationRunSegment

                _write_forecast_progress(
                    run_id, 30, f"Loading segment artifact for '{segment_key}'…"
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
                _write_forecast_progress(run_id, 45, "Preparing features…")
                predicted_list, meta_rows = _score_segment(
                    seg_artifact_path, segment_key
                )
                _write_forecast_progress(run_id, 60, "Applied segment model")

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
                    _write_forecast_progress(
                        run_id,
                        35 + round(55 * (i + 1) / len(segment_refs)),
                        f"Scored segment '{seg_key}' ({i + 1}/{len(segment_refs)})",
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
                    }
                    for i in range(len(predicted_list))
                ]
                s.bulk_insert_mappings(ForecastRunResult, result_rows)
                r.status = "success"
                r.finished_at = datetime.now(timezone.utc)
                r.progress = 100
                s.add(r)

            _write_forecast_progress(run_id, 100, "Forecast completed successfully")

        except Exception as exc:
            logger.error(f"Forecast run {run_id} failed: {exc}", exc_info=True)
            with app_session() as s:
                r = ForecastRun.query.filter_by(run_id=run_id).first()
                if r:
                    r.status = "failed"
                    r.finished_at = datetime.now(timezone.utc)
                    r.error_message = str(exc)
                    s.add(r)
            _write_forecast_progress(run_id, -1, f"Failed: {exc}")
            raise


def _cr_log(
    cr_run_id: str, message: str, level: str = "info", progress: int | None = None
):
    """Write a log line for a credit risk run. Silent-fails so the task is never blocked."""
    try:
        from project import app_session
        from project.db_models.credit_models import CreditRiskRun, CreditRiskRunLog

        now = datetime.now(timezone.utc).strftime("%H:%M:%S")
        with app_session() as s:
            s.add(
                CreditRiskRunLog(run_id=cr_run_id, t=now, level=level, message=message)
            )
            if progress is not None:
                r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                if r:
                    r.progress = progress
                    s.add(r)
    except Exception as _e:
        logger.warning(f"_cr_log failed: {_e}")


@celery_app.task(bind=True, name="run_credit_analysis")
def run_credit_analysis(self, cr_run_id: str):
    app = _make_flask_app()
    with app.app_context():
        from project import app_session
        from project.api.credit_risk.routes import _pd_rating_df
        from project.core.credit_risk.ecl import compute_ecl
        from project.core.credit_risk.kmv import run_kmv
        from project.db_models.calibration_models import Dataset
        from project.db_models.credit_models import CreditRiskResult, CreditRiskRun
        from project.db_models.forecast_models import ForecastRun, ForecastRunResult

        cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
        if not cr:
            logger.error(f"CreditRiskRun {cr_run_id} not found")
            return

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
            from project.db_models.calibration_models import (
                CalibrationRun,
                CalibrationRunSegment,
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
                fr_rows = (
                    ForecastRunResult.query.filter_by(forecast_run_id=fr.id)
                    .order_by(ForecastRunResult.id)
                    .all()
                )
                if not fr_rows:
                    raise ValueError(
                        f"Forecast run for '{key}' ({fr_run_uuid[:8]}…) has no results"
                    )

                seg_info = {"split_by": {}, "top_values": {}, "fallback": {}}
                cal_run_for_key = CalibrationRun.query.get(fr.calibration_run_id)
                if cal_run_for_key and cal_run_for_key.seg_sectors_json:
                    cal_segments = CalibrationRunSegment.query.filter_by(
                        calibration_run_id=cal_run_for_key.id, status="success"
                    ).all()
                    for s in cal_segments:
                        seg_info["split_by"][s.sector] = s.split_by
                        seg_info["top_values"].setdefault(s.sector, set()).add(
                            s.split_value
                        )
                        seg_info["fallback"].setdefault(s.sector, s.segment_key)
                forecast_segmentation[key] = seg_info

                idx_map: dict[str | None, dict[str, dict[int, float]]] = {}
                for row in fr_rows:
                    meta = json.loads(row.meta_json or "{}")
                    ctx = meta.get("segment_key")
                    scen = str(meta.get("scenario", "Baseline"))
                    try:
                        yr = int(pd.to_datetime(str(row.date)).year)
                    except Exception:
                        yr = int(str(row.date)[:4]) if row.date else 2024
                    if row.predicted is not None:
                        idx_map.setdefault(ctx, {}).setdefault(scen, {})[yr] = float(
                            row.predicted
                        )
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

            def _resolve_segment_key(
                seg_info: dict, sector: str, subsector: str, country: str
            ) -> str | None:
                split_by = seg_info["split_by"].get(sector)
                if not split_by:
                    return None
                split_val = subsector if split_by == "subsector" else country
                top_vals = seg_info["top_values"].get(sector, set())
                if split_val in top_vals:
                    return f"{sector}__{split_val}"
                if "Others" in top_vals:
                    return f"{sector}__Others"
                return seg_info["fallback"].get(sector)

            def _lookup_forecast(
                key: str, sector: str, subsector: str, country: str
            ) -> dict:
                seg_info = forecast_segmentation[key]
                var_map = forecast_by_var[key]
                if seg_info["split_by"]:
                    target = _resolve_segment_key(seg_info, sector, subsector, country)
                    if target and target in var_map:
                        return var_map[target]
                return var_map.get(None, {})

            # 4. Load PD ratings
            pd_rating_df = _pd_rating_df(curve)
            if pd_rating_df.empty:
                raise ValueError("No PD ratings found — run flask db upgrade first")
            _cr_log(
                cr_run_id,
                f"Loaded PD rating table ({len(pd_rating_df)} rows, curve={curve})",
                progress=5,
            )

            # 5. Process each client
            clients_list = portfolio_df.to_dict(orient="records")
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

                # Build forecast DataFrame from the 3 calibrated variable indices.
                # If the calibration was segmented, route this client to its own
                # segment's trajectory (by sector + subsector/country); otherwise use
                # the single portfolio-wide trajectory.
                # If forecast data contains multiple scenarios (e.g. Baseline / Adverse /
                # Severely Adverse), use them directly; fall back to a single "Baseline"
                # with artificial growth multipliers when the data has no scenario dimension.
                ta_by_scen = _lookup_forecast(
                    "total_assets", sector, subsector, country
                )
                cl_by_scen = _lookup_forecast(
                    "short_term_debts", sector, subsector, country
                )
                nc_by_scen = _lookup_forecast(
                    "long_term_debts", sector, subsector, country
                )

                all_scens = sorted(set(ta_by_scen) & set(cl_by_scen) & set(nc_by_scen))
                if not all_scens:
                    # Flatten any single-scenario data for the fallback path
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
                    )
                    continue
                forecast = pd.DataFrame(rows_fc)

                try:
                    kmv_df = run_kmv(com_info, forecast, pd_rating_df)
                    ecl_df = compute_ecl(
                        kmv_df, exposure, discount_rate, lifetime_horizon
                    )
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
                        )
                    )
                except Exception as client_err:
                    failed_clients += 1
                    _cr_log(
                        cr_run_id,
                        f"Client {client_id} failed: {client_err}",
                        level="warn",
                    )

                # Flush batch and update progress every 10 clients or at end
                if (idx + 1) % 10 == 0 or idx == n_clients - 1:
                    with app_session() as s:
                        for res in result_batch:
                            s.add(res)
                        result_batch = []
                    progress = round((idx + 1) / n_clients * 100)
                    _cr_log(
                        cr_run_id,
                        f"Processed {idx + 1}/{n_clients} clients",
                        progress=progress,
                    )

            # 6. Mark success
            summary = (
                f"Completed: {n_clients - failed_clients}/{n_clients} clients succeeded"
            )
            if failed_clients:
                summary += f" ({failed_clients} failed)"
            _cr_log(cr_run_id, summary, progress=100)
            with app_session() as s:
                r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                r.status = "success"
                r.finished_at = datetime.now(timezone.utc)
                r.progress = 100
                s.add(r)

        except Exception as exc:
            logger.error(f"Credit risk run {cr_run_id} failed: {exc}", exc_info=True)
            _cr_log(cr_run_id, f"Analysis failed: {exc}", level="error")
            with app_session() as s:
                r = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
                if r:
                    r.status = "failed"
                    r.finished_at = datetime.now(timezone.utc)
                    r.error_message = str(exc)
                    s.add(r)
            raise
