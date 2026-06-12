import json
import uuid
from datetime import datetime, timezone
from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from project import db, app_session
from project.db_models.calibration_models import CalibrationRun, Dataset, ModelConfig, Forecast
from project.workers.tasks import run_calibration
from project.logger import get_logger
from . import calibrations

logger = get_logger(__name__)


@calibrations.get('/')
@jwt_required()
def list_runs():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    status_filter = request.args.get('status')

    q = (CalibrationRun.query
         .join(Dataset,      CalibrationRun.dataset_id      == Dataset.id)
         .join(ModelConfig,  CalibrationRun.model_config_id == ModelConfig.id)
         .order_by(CalibrationRun.started_at.desc()))

    if status_filter:
        q = q.filter(CalibrationRun.status == status_filter)

    runs = q.paginate(page=page, per_page=per_page, error_out=False)
    result = []
    for r in runs.items:
        d = r.to_dict()
        d['config_name']  = r.model_config.name  if r.model_config  else None
        d['dataset_name'] = r.dataset.name       if r.dataset       else None
        d['algorithm']    = r.model_config.algorithm if r.model_config else None
        result.append(d)

    return jsonify({'items': result, 'total': runs.total, 'page': page, 'pages': runs.pages}), 200


@calibrations.post('/')
@jwt_required()
def create_run():
    body = request.get_json(silent=True) or {}
    required = ('dataset_id', 'model_config_id')
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({'error': f'Missing: {missing}'}), 400

    ds  = Dataset.query.get(body['dataset_id'])
    cfg = ModelConfig.query.get(body['model_config_id'])
    if not ds:
        return jsonify({'error': 'Dataset not found'}), 404
    if not cfg:
        return jsonify({'error': 'ModelConfig not found'}), 404

    run_id = str(uuid.uuid4())
    with app_session() as session:
        run = CalibrationRun(
            run_id=run_id,
            dataset_id=ds.id,
            model_config_id=cfg.id,
            status='queued',
            triggered_by=get_jwt_identity(),
        )
        session.add(run)
        session.flush()
        result = run.to_dict()

    run_calibration.delay(run_id)
    return jsonify(result), 202


@calibrations.get('/<run_id>')
@jwt_required()
def get_run(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({'error': 'Not found'}), 404
    d = run.to_dict()
    d['config_name']  = run.model_config.name      if run.model_config  else None
    d['dataset_name'] = run.dataset.name           if run.dataset       else None
    d['algorithm']    = run.model_config.algorithm if run.model_config  else None
    return jsonify(d), 200


@calibrations.get('/<run_id>/diagnostics')
@jwt_required()
def get_diagnostics(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({'error': 'Not found'}), 404
    if run.status != 'success':
        return jsonify({'error': f'Run is {run.status}, diagnostics not available'}), 409
    metrics = json.loads(run.val_metrics_json or '{}')
    return jsonify({
        'run_id':      run_id,
        'config_name': run.model_config.name      if run.model_config  else None,
        'algorithm':   run.model_config.algorithm if run.model_config  else None,
        'metrics':     metrics
    }), 200


@calibrations.get('/<run_id>/forecast')
@jwt_required()
def get_forecast(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({'error': 'Not found'}), 404
    forecasts = Forecast.query.filter_by(calibration_run_id=run.id).order_by(Forecast.created_at).all()
    return jsonify([f.to_dict() for f in forecasts]), 200


@calibrations.post('/<run_id>/recalibrate')
@jwt_required()
def recalibrate(run_id):
    original = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not original:
        return jsonify({'error': 'Not found'}), 404

    body = request.get_json(silent=True) or {}
    new_dataset_id = body.get('dataset_id', original.dataset_id)
    new_run_id = str(uuid.uuid4())

    with app_session() as session:
        run = CalibrationRun(
            run_id=new_run_id,
            dataset_id=new_dataset_id,
            model_config_id=original.model_config_id,
            status='queued',
            triggered_by=get_jwt_identity(),
        )
        session.add(run)
        session.flush()
        result = run.to_dict()

    run_calibration.delay(new_run_id)
    return jsonify(result), 202
