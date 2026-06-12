from flask import jsonify
from flask_jwt_extended import jwt_required
from project.db_models.calibration_models import CalibrationRun, Forecast
from . import forecasts


@forecasts.get('/<run_id>')
@jwt_required()
def get_forecast(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({'error': 'Not found'}), 404
    rows = Forecast.query.filter_by(calibration_run_id=run.id).order_by(Forecast.created_at).all()
    return jsonify([r.to_dict() for r in rows]), 200
