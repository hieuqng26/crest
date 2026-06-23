import json

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity
from pydantic import ValidationError

from project import app_session
from project.api.auth.decorators import require_perm
from project.core.model_registry import REGISTRY, get_model_class, registry_metadata
from project.db_models.calibration_models import CalibrationRun, ModelConfig
from project.logger import get_logger

from . import model_configs

logger = get_logger(__name__)


@model_configs.get("/registry")
@require_perm("model_config:read")
def list_registry():
    return jsonify(registry_metadata()), 200


@model_configs.get("/")
@require_perm("model_config:read")
def list_configs():
    rows = ModelConfig.query.order_by(ModelConfig.created_at.desc()).all()
    return jsonify([r.to_dict() for r in rows]), 200


@model_configs.post("/")
@require_perm("model_config:write")
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
@require_perm("model_config:read")
def get_config(config_id):
    cfg = ModelConfig.query.filter_by(id=config_id).first()
    if not cfg:
        return jsonify({"error": "Not found"}), 404
    return jsonify(cfg.to_dict()), 200


@model_configs.patch("/<int:config_id>")
@require_perm("model_config:write")
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


def _cal_refs_for(config_id: int):
    return CalibrationRun.query.filter_by(model_config_id=config_id).all()


@model_configs.get("/<int:config_id>/refs")
@require_perm("model_config:read")
def get_refs(config_id: int):
    cfg = ModelConfig.query.filter_by(id=config_id).first()
    if not cfg:
        return jsonify({"error": "Not found"}), 404
    runs = _cal_refs_for(config_id)
    return jsonify(
        {
            "calibration_runs": [
                {"run_id": r.run_id, "status": r.status, "target_col": r.target_col}
                for r in runs
            ]
        }
    ), 200


@model_configs.delete("/<int:config_id>")
@require_perm("model_config:write")
def delete_config(config_id):
    cfg = ModelConfig.query.filter_by(id=config_id).first()
    if not cfg:
        return jsonify({"error": "Not found"}), 404
    refs = _cal_refs_for(config_id)
    if refs:
        return jsonify(
            {
                "message": f"Cannot delete: {len(refs)} calibration run(s) reference this configuration.",
                "dependencies": {"calibration_runs": len(refs)},
            }
        ), 409
    with app_session() as session:
        session.delete(cfg)
    return "", 204


@model_configs.post("/bulk-delete")
@require_perm("model_config:write")
def bulk_delete_configs():
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    if not ids:
        return jsonify({"error": "ids is required"}), 400
    deleted = 0
    blocked = []
    for cid in ids:
        cfg = ModelConfig.query.filter_by(id=cid).first()
        if not cfg:
            continue
        if _cal_refs_for(cid):
            blocked.append(cid)
            continue
        with app_session() as session:
            session.delete(cfg)
        deleted += 1
    if blocked:
        return jsonify(
            {
                "message": f"Deleted {deleted}, skipped {len(blocked)} config(s) with dependent calibration runs.",
                "deleted": deleted,
                "blocked": blocked,
            }
        ), 207
    return jsonify({"deleted": deleted}), 200
