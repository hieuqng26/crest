from flask import jsonify
from flask_jwt_extended import jwt_required
from project.db_models.calibration_models import CalibrationRun
from . import evaluations
import json


@evaluations.get('/<run_id>')
@jwt_required()
def get_evaluation(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({'error': 'Not found'}), 404
    if run.status != 'success':
        return jsonify({'error': f'Run is {run.status}'}), 409
    return jsonify({
        'run_id':      run_id,
        'config_name': run.model_config.name      if run.model_config else None,
        'algorithm':   run.model_config.algorithm if run.model_config else None,
        'metrics':     json.loads(run.val_metrics_json or '{}')
    }), 200
