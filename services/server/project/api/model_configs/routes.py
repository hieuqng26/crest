import json

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from pydantic import ValidationError

from project import app_session
from project.core.model_registry import REGISTRY, get_model_class, registry_metadata
from project.db_models.calibration_models import ModelConfig
from project.logger import get_logger

from . import model_configs

logger = get_logger(__name__)


@model_configs.get("/registry")
@jwt_required()
def list_registry():
    return jsonify(registry_metadata()), 200


@model_configs.get("/")
@jwt_required()
def list_configs():
    rows = ModelConfig.query.order_by(ModelConfig.created_at.desc()).all()
    return jsonify([r.to_dict() for r in rows]), 200


@model_configs.post("/")
@jwt_required()
def create_config():
    body = request.get_json(silent=True) or {}
    required = ("name", "algorithm")
    missing = [f for f in required if not body.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {missing}"}), 400

    algorithm = body["algorithm"]
    if algorithm not in REGISTRY:
        return jsonify({"error": f"Unknown algorithm '{algorithm}'"}), 400

    # Validate hyperparams against Pydantic schema
    plugin_cls = get_model_class(algorithm)
    raw_params = body.get("hyperparams", {})
    try:
        plugin_cls.param_schema(**raw_params)
    except ValidationError as e:
        return jsonify({"error": "Invalid hyperparameters", "detail": e.errors()}), 422

    train_split = float(body.get("train_split", 0.8))
    scaler = body.get("scaler") or None
    search_config_raw = body.get("search_config")
    search_config_json_val = (
        json.dumps(search_config_raw) if search_config_raw else None
    )

    with app_session() as session:
        cfg = ModelConfig(
            name=body["name"],
            family=REGISTRY[algorithm].family,
            algorithm=algorithm,
            hyperparams_json=json.dumps(raw_params),
            train_split=train_split,
            scaler=scaler,
            search_config_json=search_config_json_val,
            created_by=get_jwt_identity(),
        )
        session.add(cfg)
        session.flush()
        result = cfg.to_dict()

    return jsonify(result), 201


@model_configs.get("/<int:config_id>")
@jwt_required()
def get_config(config_id):
    cfg = ModelConfig.query.filter_by(id=config_id).first()
    if not cfg:
        return jsonify({"error": "Not found"}), 404
    return jsonify(cfg.to_dict()), 200


@model_configs.patch("/<int:config_id>")
@jwt_required()
def update_config(config_id):
    body = request.get_json(silent=True) or {}

    with app_session() as session:
        cfg = ModelConfig.query.filter_by(id=config_id).first()
        if not cfg:
            return jsonify({"error": "Not found"}), 404

        algorithm = body.get("algorithm", cfg.algorithm)
        if algorithm not in REGISTRY:
            return jsonify({"error": f"Unknown algorithm '{algorithm}'"}), 400

        raw_params = body.get("hyperparams", json.loads(cfg.hyperparams_json or "{}"))
        plugin_cls = get_model_class(algorithm)
        try:
            plugin_cls.param_schema(**raw_params)
        except ValidationError as e:
            return jsonify(
                {"error": "Invalid hyperparameters", "detail": e.errors()}
            ), 422

        if "name" in body:
            cfg.name = body["name"]
        cfg.algorithm = algorithm
        cfg.family = REGISTRY[algorithm].family
        cfg.hyperparams_json = json.dumps(raw_params)
        if "train_split" in body:
            cfg.train_split = float(body["train_split"])
        if "scaler" in body:
            cfg.scaler = body.get("scaler") or None
        if "search_config" in body:
            cfg.search_config_json = (
                json.dumps(body["search_config"]) if body["search_config"] else None
            )
        session.add(cfg)
        session.flush()
        result = cfg.to_dict()

    return jsonify(result), 200


@model_configs.delete("/<int:config_id>")
@jwt_required()
def delete_config(config_id):
    with app_session() as session:
        cfg = ModelConfig.query.filter_by(id=config_id).first()
        if not cfg:
            return jsonify({"error": "Not found"}), 404
        session.delete(cfg)
    return "", 204


@model_configs.post("/bulk-delete")
@jwt_required()
def bulk_delete_configs():
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    if not ids:
        return jsonify({"error": "ids is required"}), 400
    deleted = 0
    for cid in ids:
        with app_session() as session:
            cfg = ModelConfig.query.filter_by(id=cid).first()
            if not cfg:
                continue
            session.delete(cfg)
        deleted += 1
    return jsonify({"deleted": deleted}), 200
