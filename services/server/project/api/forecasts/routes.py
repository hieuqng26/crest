from flask import jsonify

from project.api.auth.decorators import require_perm
from project.db_models.calibration_models import CalibrationRun, Forecast
from project.workers.tasks import _load_forecast_data

from . import forecasts


@forecasts.get("/<run_id>")
@require_perm("forecast:read")
def get_forecast(run_id):
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run:
        return jsonify({"error": "Not found"}), 404
    rows = (
        Forecast.query.filter_by(calibration_run_id=run.id)
        .order_by(Forecast.created_at)
        .all()
    )
    result = []
    for r in rows:
        d = r.to_dict()
        d["forecast_json"] = _load_forecast_data(r)
        result.append(d)
    return jsonify(result), 200
