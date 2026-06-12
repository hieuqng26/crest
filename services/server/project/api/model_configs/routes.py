import json
from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from pydantic import ValidationError
from project import db, app_session
from project.db_models.calibration_models import ModelConfig
from project.core.model_registry import REGISTRY, registry_metadata, get_model_class
from project.logger import get_logger
from . import model_configs

logger = get_logger(__name__)


@model_configs.get('/registry')
@jwt_required()
def list_registry():
    return jsonify(registry_metadata()), 200


@model_configs.get('/')
@jwt_required()
def list_configs():
    rows = ModelConfig.query.order_by(ModelConfig.created_at.desc()).all()
    return jsonify([r.to_dict() for r in rows]), 200


@model_configs.post('/')
@jwt_required()
def create_config():
    body = request.get_json(silent=True) or {}
    required = ('name', 'algorithm')
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({'error': f'Missing fields: {missing}'}), 400

    algorithm = body['algorithm']
    if algorithm not in REGISTRY:
        return jsonify({'error': f"Unknown algorithm '{algorithm}'"}), 400

    # Validate hyperparams against Pydantic schema
    plugin_cls = get_model_class(algorithm)
    raw_params = body.get('hyperparams', {})
    try:
        plugin_cls.param_schema(**raw_params)
    except ValidationError as e:
        return jsonify({'error': 'Invalid hyperparameters', 'detail': e.errors()}), 422

    with app_session() as session:
        cfg = ModelConfig(
            name=body['name'],
            family=REGISTRY[algorithm].family,
            algorithm=algorithm,
            hyperparams_json=json.dumps(raw_params),
            feature_cols_json=json.dumps(body.get('feature_cols', [])),
            target_col=body.get('target_col', ''),
            created_by=get_jwt_identity()
        )
        session.add(cfg)
        session.flush()
        result = cfg.to_dict()

    return jsonify(result), 201


@model_configs.get('/<int:config_id>')
@jwt_required()
def get_config(config_id):
    cfg = ModelConfig.query.filter_by(id=config_id).first()
    if not cfg:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(cfg.to_dict()), 200
