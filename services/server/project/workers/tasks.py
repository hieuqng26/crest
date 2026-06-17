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
        secondary_dataset_ids = json.loads(initial.secondary_dataset_ids_json or "[]")
        merge_steps = json.loads(initial.merge_steps_json or "[]")

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

            # --- 2b. Merge secondary datasets ---
            if secondary_dataset_ids and merge_steps:
                for step_idx, sec_id in enumerate(secondary_dataset_ids):
                    sec_ds = Dataset.query.get(sec_id)
                    if not sec_ds or not sec_ds.file_path:
                        raise ValueError(
                            f"Secondary dataset {sec_id} not found or has no file"
                        )
                    sec_bytes = storage.download_bytes(
                        sec_ds.file_path.split("/", 1)[-1]
                    )
                    sec_ext = sec_ds.file_path.rsplit(".", 1)[-1].lower()
                    sec_buf = io.BytesIO(sec_bytes)
                    if sec_ext == "csv":
                        sec_df = pd.read_csv(sec_buf)
                    elif sec_ext == "xlsx":
                        sec_df = pd.read_excel(sec_buf)
                    elif sec_ext == "parquet":
                        sec_df = pd.read_parquet(sec_buf)
                    else:
                        raise ValueError(
                            f"Unsupported file type for secondary dataset: {sec_ext}"
                        )

                    step = merge_steps[step_idx] if step_idx < len(merge_steps) else {}
                    merge_type = step.get("type", "inner")
                    join_keys = step.get("on") or []

                    if merge_type == "union":
                        shared_cols = [c for c in df.columns if c in sec_df.columns]
                        df = pd.concat(
                            [df[shared_cols], sec_df[shared_cols]], ignore_index=True
                        )
                    else:
                        how = (
                            merge_type
                            if merge_type in ("inner", "left", "outer", "right")
                            else "inner"
                        )
                        if not join_keys:
                            raise ValueError(
                                f"Merge step {step_idx + 1}: no join keys specified for {how} join"
                            )
                        df = df.merge(sec_df, on=join_keys, how=how)

                    _write_progress(
                        run_id,
                        20 + step_idx + 1,
                        f"Merged dataset {sec_ds.name} ({merge_type}) → {len(df):,} rows · {len(df.columns)} cols",
                    )

            # --- 3. Feature prep ---
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
                s.add(
                    Forecast(
                        calibration_run_id=r.id,
                        forecast_horizon=len(y_val),
                        forecast_json=json.dumps(
                            {
                                "actual": [
                                    float(v) if v is not None else None
                                    for v in y_val.tolist()
                                ],
                                "predicted": [
                                    float(v) if v is not None else None
                                    for v in y_val_pred.tolist()
                                ],
                                "meta": {
                                    col: [
                                        v
                                        if (v is None or isinstance(v, (str, bool)))
                                        else (
                                            float(v)
                                            if isinstance(v, float)
                                            else int(v)
                                            if isinstance(v, (int, np.integer))
                                            else str(v)
                                        )
                                        for v in df_val_meta[col].tolist()
                                    ]
                                    for col in meta_cols
                                },
                            }
                        ),
                    )
                )
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
        from project.core.credit_risk.mock_credit import mock_kmv_forecast
        from project.db_models.calibration_models import (
            CalibrationRun,
            Dataset,
            Forecast,
        )
        from project.db_models.credit_models import CreditRiskResult, CreditRiskRun

        cr = CreditRiskRun.query.filter_by(run_id=cr_run_id).first()
        if not cr:
            logger.error(f"CreditRiskRun {cr_run_id} not found")
            return

        dataset_id = cr.dataset_id
        cal_run_ids = json.loads(cr.cal_run_ids_json or "[]")
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
            ds = Dataset.query.get(dataset_id)
            if not ds or not ds.file_path:
                raise ValueError(f"Dataset {dataset_id} not found or has no file")
            # Extract scalars before any app_session() call closes the default session
            ds_name = ds.name
            ds_file_path = ds.file_path

            _cr_log(cr_run_id, f"Loading dataset: {ds_name}")
            file_bytes = storage.download_bytes(ds_file_path.split("/", 1)[-1])
            ext = ds_file_path.rsplit(".", 1)[-1].lower()
            buf = io.BytesIO(file_bytes)
            if ext == "csv":
                credit_df = pd.read_csv(buf)
            elif ext == "xlsx":
                credit_df = pd.read_excel(buf)
            elif ext == "parquet":
                credit_df = pd.read_parquet(buf)
            else:
                raise ValueError(f"Unsupported file type: {ext}")

            required = {
                "client_id",
                "market_cap",
                "vol_equity",
                "risk_free_rate",
                "rating",
            }
            missing = required - set(credit_df.columns)
            if missing:
                raise ValueError(f"Credit dataset missing required columns: {missing}")

            n_clients = len(credit_df)
            _cr_log(cr_run_id, f"Loaded {n_clients} clients from dataset", progress=2)

            # 3. Build balance sheet forecast index from all provided calibration runs.
            #    Each recognized cal run contributes its predicted values; later entries
            #    overwrite earlier ones for the same (client_id, year) tuple.
            recognized = {"total_asset", "assets", "asset", "total_assets"}
            cal_forecast_index: dict | None = None

            if cal_run_ids:
                _cr_log(
                    cr_run_id, f"Processing {len(cal_run_ids)} calibration input(s)"
                )
            else:
                _cr_log(cr_run_id, "No calibration inputs — using synthetic scenarios")

            for cal_run_id in cal_run_ids:
                cal_run = CalibrationRun.query.filter_by(run_id=cal_run_id).first()
                if not cal_run or cal_run.status != "success":
                    _cr_log(
                        cr_run_id,
                        f"Skipping cal run {cal_run_id[:8]}… (not found or not successful)",
                        level="warn",
                    )
                    continue
                # Extract all needed scalars before any _cr_log call closes the session
                cal_run_db_id = cal_run.id
                target_col = cal_run.target_col or ""
                if target_col.lower() not in recognized:
                    _cr_log(
                        cr_run_id,
                        f"Skipping cal run {cal_run_id[:8]}… (target_col={target_col!r} not a balance sheet variable)",
                        level="warn",
                    )
                    continue
                _cr_log(
                    cr_run_id,
                    f"Using cal run {cal_run_id[:8]}… (target_col={target_col})",
                )
                cal_forecasts = Forecast.query.filter_by(
                    calibration_run_id=cal_run_db_id
                ).all()
                if not cal_forecasts:
                    continue
                # Extract forecast_json before the loop's _cr_log calls close the session
                forecast_json_str = cal_forecasts[0].forecast_json or "{}"
                try:
                    fdata = json.loads(forecast_json_str)
                    predicted = fdata.get("predicted", [])
                    meta = fdata.get("meta", {})
                    dates = meta.get("date", [])
                    cids = meta.get("client_id", [])
                    cl_vals = meta.get("CL", [])
                    noncl_vals = meta.get("NonCL", [])

                    if cal_forecast_index is None:
                        cal_forecast_index = {}

                    for i, cid in enumerate(cids):
                        if cid not in cal_forecast_index:
                            cal_forecast_index[cid] = []
                        try:
                            yr = int(pd.to_datetime(str(dates[i])).year)
                        except Exception:
                            yr = int(str(dates[i])[:4]) if dates else 2024
                        ta = float(predicted[i]) if i < len(predicted) else None
                        cl = (
                            float(cl_vals[i])
                            if i < len(cl_vals) and cl_vals[i] is not None
                            else None
                        )
                        nc = (
                            float(noncl_vals[i])
                            if i < len(noncl_vals) and noncl_vals[i] is not None
                            else None
                        )
                        if ta is not None:
                            # Overwrite any existing entry for this (cid, yr)
                            cal_forecast_index[cid] = [
                                e for e in cal_forecast_index[cid] if e[0] != yr
                            ]
                            cal_forecast_index[cid].append((yr, ta, cl, nc))
                except Exception as fe:
                    logger.warning(
                        f"Could not parse calibration forecast {cal_run_id} for {cr_run_id}: {fe}"
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

            # 5. Process each client
            clients_list = credit_df.to_dict(orient="records")
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

                # Build forecast DataFrame — from calibration data or mock
                if cal_forecast_index is not None and client_id in cal_forecast_index:
                    entries = sorted(cal_forecast_index[client_id], key=lambda x: x[0])
                    years = [e[0] for e in entries]
                    baseline_ta = [e[1] for e in entries]
                    baseline_cl = [
                        e[2] if e[2] is not None else e[1] * 0.20 for e in entries
                    ]
                    baseline_nc = [
                        e[3] if e[3] is not None else e[1] * 0.30 for e in entries
                    ]
                    rows_fc = []
                    for scen, growth in [
                        ("Baseline", 1.0),
                        ("Upside", 1.02),
                        ("Downside", 0.98),
                    ]:
                        for j, yr in enumerate(years):
                            factor = growth**j
                            ta = baseline_ta[j] * factor
                            ratio = ta / baseline_ta[j] if baseline_ta[j] else 1.0
                            rows_fc.append(
                                {
                                    "YEAR": yr,
                                    "SCENARIO": scen,
                                    "Total_Asset": ta,
                                    "CL": baseline_cl[j] * ratio,
                                    "NonCL": baseline_nc[j] * ratio,
                                }
                            )
                    forecast = pd.DataFrame(rows_fc)
                else:
                    forecast = mock_kmv_forecast(client_id, base_year=2024, n_years=10)

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
