import json
from flask import jsonify, request
from flask_jwt_extended import jwt_required
from project.db_models.calibration_models import CalibrationRun
from . import credit_risk


def _load_metrics(run_id: str) -> dict | None:
    run = CalibrationRun.query.filter_by(run_id=run_id).first()
    if not run or run.status != 'success':
        return None
    return json.loads(run.val_metrics_json or '{}')


@credit_risk.post('/ecl')
@jwt_required()
def compute_ecl():
    body = request.get_json(silent=True) or {}
    portfolio = body.get('portfolio', [])
    if not portfolio:
        return jsonify({'error': 'portfolio is required'}), 400

    results = []
    total_ecl = 0.0
    stage_ecl: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0}

    for seg in portfolio:
        ead   = float(seg.get('ead', 0))
        pd_   = float(seg.get('pd',  0))
        lgd   = float(seg.get('lgd', 0))
        stage = int(seg.get('stage', 1))
        ecl   = ead * pd_ * lgd
        total_ecl += ecl
        stage_ecl[stage] = stage_ecl.get(stage, 0.0) + ecl
        results.append({**seg, 'ecl': round(ecl, 2)})

    return jsonify({
        'total_ecl':       round(total_ecl, 2),
        'stage_breakdown': [{'stage': k, 'ecl': round(v, 2)} for k, v in stage_ecl.items()],
        'segments':        results
    }), 200


@credit_risk.post('/pd-lgd')
@jwt_required()
def compute_pd_lgd():
    body = request.get_json(silent=True) or {}
    run_ids  = body.get('run_ids', [])
    horizons = body.get('horizons', [1, 2, 3, 5, 7, 10])

    curves = []
    for run_id in run_ids:
        metrics = _load_metrics(run_id)
        if not metrics:
            continue
        run = CalibrationRun.query.filter_by(run_id=run_id).first()
        base_pd  = max(0.001, metrics.get('auc_roc', 0.5) - 0.5)
        pd_curve  = [round(min(1.0, base_pd * h ** 0.7), 4) for h in horizons]
        lgd_curve = [round(min(1.0, 0.40 + 0.02 * h), 4) for h in horizons]
        curves.append({
            'run_id':      run_id,
            'config_name': run.model_config.name if run and run.model_config else run_id,
            'horizons':    horizons,
            'pd':          pd_curve,
            'lgd':         lgd_curve
        })

    return jsonify({'curves': curves}), 200
