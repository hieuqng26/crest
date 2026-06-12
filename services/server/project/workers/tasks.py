import json
import uuid
import pickle
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import mlflow
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, MinMaxScaler, RobustScaler
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV

from project.workers import celery_app
from project.logger import get_logger
from project.core import storage
from project.core.model_registry import get_model_class

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Calibration task
# ---------------------------------------------------------------------------


def _make_flask_app():
    """Import create_app lazily to avoid circular imports inside worker."""
    from project import create_app
    return create_app()


def _get_scaler(name: str):
    return {
        'standard': StandardScaler(),
        'minmax':   MinMaxScaler(),
        'robust':   RobustScaler(),
    }.get(name)


def _emit(run_id: str, progress: int, message: str):
    try:
        from project import send_notification
        send_notification('calibration_progress', {
            'run_id': run_id,
            'progress': progress,
            'message': message
        })
    except Exception:
        pass


@celery_app.task(bind=True, name='run_calibration')
def run_calibration(self, run_id: str):
    app = _make_flask_app()
    with app.app_context():
        from project import db, app_session
        from project.db_models.calibration_models import CalibrationRun, Dataset, ModelConfig, Forecast

        run = CalibrationRun.query.filter_by(run_id=run_id).first()
        if not run:
            logger.error(f"CalibrationRun {run_id} not found")
            return

        try:
            # --- 1. Mark running ---
            with app_session() as s:
                run.status = 'running'
                run.started_at = datetime.now(timezone.utc)
                s.add(run)
            _emit(run_id, 5, 'Loading dataset…')

            # --- 2. Load data ---
            ds: Dataset = Dataset.query.get(run.dataset_id)
            cfg: ModelConfig = ModelConfig.query.get(run.model_config_id)

            schema = json.loads(ds.schema_json or '{}')
            columns = schema.get('columns', [])

            if ds.file_path:
                file_bytes = storage.download_bytes(ds.file_path.split('/', 1)[-1])
                ext = ds.file_path.rsplit('.', 1)[-1].lower()
                import io
                buf = io.BytesIO(file_bytes)
                if ext == 'csv':     df = pd.read_csv(buf)
                elif ext == 'xlsx':  df = pd.read_excel(buf)
                elif ext == 'parquet': df = pd.read_parquet(buf)
                else:
                    raise ValueError(f"Unsupported file type: {ext}")
            else:
                raise ValueError("No file path on dataset — live query results must be cached first")

            _emit(run_id, 20, f'Loaded {len(df):,} rows · {len(df.columns)} columns')

            # --- 3. Feature prep ---
            target_col = cfg.target_col
            feature_cols = json.loads(cfg.feature_cols_json or '[]') or [c for c in df.columns if c != target_col]

            X = df[feature_cols].select_dtypes(include=[np.number]).values
            y = df[target_col].values

            train_split = run.train_split if hasattr(run, 'train_split') else 0.8
            X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=1 - train_split, random_state=42)

            scaler_name = getattr(run, 'scaler', None)
            scaler = _get_scaler(scaler_name) if scaler_name and scaler_name != 'none' else None
            if scaler:
                X_train = scaler.fit_transform(X_train)
                X_val   = scaler.transform(X_val)
            _emit(run_id, 35, 'Feature prep complete')

            # --- 4. Init model + hyperparams ---
            plugin_cls = get_model_class(cfg.algorithm)
            plugin = plugin_cls()
            raw_params = json.loads(cfg.hyperparams_json or '{}')
            params_obj = plugin_cls.param_schema(**raw_params)

            # --- 5. MLflow + fit ---
            mlflow_uri = os.getenv('MLFLOW_TRACKING_URI', 'http://mlflow:5000')
            mlflow.set_tracking_uri(mlflow_uri)
            mlflow.set_experiment(cfg.name)

            with mlflow.start_run(run_name=run_id) as mlflow_run:
                mlflow.log_params(raw_params)
                _emit(run_id, 50, f'Fitting {cfg.algorithm}…')
                plugin.fit(X_train, y_train, params_obj)
                _emit(run_id, 75, 'Computing diagnostics…')

                # --- 6. Diagnostics ---
                diag = plugin.diagnostics(X_val, y_val)
                scalar_metrics = {k: v for k, v in diag.items() if isinstance(v, (int, float))}
                mlflow.log_metrics(scalar_metrics)

                # Train metrics (simple)
                y_train_pred = plugin.predict(X_train)
                from sklearn.metrics import roc_auc_score
                try:
                    train_auc = float(roc_auc_score(y_train, y_train_pred))
                    mlflow.log_metric('train_auc_roc', train_auc)
                    train_metrics = {'auc_roc': train_auc}
                except Exception:
                    train_metrics = {}

                # --- 7. Save artifact ---
                artifact_obj = {'model': plugin, 'scaler': scaler, 'feature_cols': feature_cols}
                artifact_bytes = pickle.dumps(artifact_obj)
                object_name = f"artifacts/{run_id}/model.pkl"
                artifact_path = storage.upload_bytes(object_name, artifact_bytes, 'application/octet-stream')
                mlflow.log_artifact.__doc__  # no-op reference to avoid unused import warning

                mlflow_run_id = mlflow_run.info.run_id

            # --- 8. Persist metrics + success ---
            with app_session() as s:
                run.status = 'success'
                run.finished_at = datetime.now(timezone.utc)
                run.mlflow_run_id = mlflow_run_id
                run.artifact_path = artifact_path
                run.val_metrics_json = json.dumps(diag)
                run.train_metrics_json = json.dumps(train_metrics)
                s.add(run)
            _emit(run_id, 100, 'Run completed successfully')

        except Exception as exc:
            logger.error(f"Calibration run {run_id} failed: {exc}", exc_info=True)
            with app_session() as s:
                run.status = 'failed'
                run.finished_at = datetime.now(timezone.utc)
                run.error_message = str(exc)
                s.add(run)
            _emit(run_id, -1, f'Failed: {exc}')
            raise
