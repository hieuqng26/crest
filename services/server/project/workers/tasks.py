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

            target_col = initial_target_col or cfg.target_col
            algorithm = cfg.algorithm
            raw_params = json.loads(cfg.hyperparams_json or "{}")
            feature_cols_json = json.loads(
                initial_feature_cols_json or cfg.feature_cols_json or "[]"
            )
            search_cfg = json.loads(search_config_json or "null")

            _write_progress(
                run_id, 20, f"Loaded {len(df):,} rows · {len(df.columns)} columns"
            )

            # --- 2b. Merge secondary datasets ---
            if secondary_dataset_ids and merge_steps:
                for step_idx, sec_id in enumerate(secondary_dataset_ids):
                    sec_ds = Dataset.query.get(sec_id)
                    if not sec_ds or not sec_ds.file_path:
                        raise ValueError(f"Secondary dataset {sec_id} not found or has no file")
                    sec_bytes = storage.download_bytes(sec_ds.file_path.split("/", 1)[-1])
                    sec_ext = sec_ds.file_path.rsplit(".", 1)[-1].lower()
                    sec_buf = io.BytesIO(sec_bytes)
                    if sec_ext == "csv":
                        sec_df = pd.read_csv(sec_buf)
                    elif sec_ext == "xlsx":
                        sec_df = pd.read_excel(sec_buf)
                    elif sec_ext == "parquet":
                        sec_df = pd.read_parquet(sec_buf)
                    else:
                        raise ValueError(f"Unsupported file type for secondary dataset: {sec_ext}")

                    step = merge_steps[step_idx] if step_idx < len(merge_steps) else {}
                    merge_type = step.get("type", "inner")
                    join_keys = step.get("on") or []

                    if merge_type == "union":
                        shared_cols = [c for c in df.columns if c in sec_df.columns]
                        df = pd.concat([df[shared_cols], sec_df[shared_cols]], ignore_index=True)
                    else:
                        how = merge_type if merge_type in ("inner", "left", "outer", "right") else "inner"
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
            feature_cols = feature_cols_json or [
                c for c in df.columns if c != target_col
            ]
            X = df[feature_cols].select_dtypes(include=[np.number]).values
            y = df[target_col].values

            # Split by index so metadata rows stay aligned with val predictions
            idx = np.arange(len(df))
            idx_train, idx_val = train_test_split(
                idx, test_size=round(1.0 - train_split_ratio, 4), random_state=42
            )
            X_train, X_val = X[idx_train], X[idx_val]
            y_train, y_val = y[idx_train], y[idx_val]

            # Metadata = every column that isn't a feature and isn't the target
            meta_cols = [c for c in df.columns if c not in feature_cols and c != target_col]
            df_val_meta = df.iloc[idx_val][meta_cols].reset_index(drop=True)

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
                    train_metrics = {"auc_roc": float(roc_auc_score(y_train, y_train_pred))}
                else:
                    train_metrics = {
                        "r2": float(r2_score(y_train, y_train_pred)),
                        "rmse": float(np.sqrt(mean_squared_error(y_train, y_train_pred))),
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
                                        v if (v is None or isinstance(v, (str, bool))) else (
                                            float(v) if isinstance(v, float) else
                                            int(v) if isinstance(v, (int, np.integer)) else str(v)
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
