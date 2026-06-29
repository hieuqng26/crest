import json

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from project import app_session
from project.api.auth.decorators import require_perm
from project.db_models.calibration_models import CalibrationRun, SegmentationConfig
from project.logger import get_logger

from . import segmentation_configs

logger = get_logger(__name__)


@segmentation_configs.get("/")
@require_perm("model_config:read")
def list_configs():
    rows = SegmentationConfig.query.order_by(SegmentationConfig.created_at.desc()).all()
    return jsonify([r.to_dict() for r in rows]), 200


@segmentation_configs.post("/")
@require_perm("model_config:write")
def create_config():
    body = request.get_json(silent=True) or {}
    if not body.get("name"):
        return jsonify({"error": "Missing field: name"}), 400
    if body.get("default_split") not in ("subsector", "country"):
        return jsonify({"error": "default_split must be 'subsector' or 'country'"}), 400

    sector_rules = body.get("sector_rules", [])
    for rule in sector_rules:
        if rule.get("split_by") not in ("subsector", "country"):
            return jsonify(
                {"error": "sector_rules[].split_by must be 'subsector' or 'country'"}
            ), 400

    with app_session() as session:
        cfg = SegmentationConfig(
            name=body["name"],
            description=body.get("description") or None,
            default_split=body["default_split"],
            max_segments=int(body.get("max_segments", 5)),
            sector_rules_json=json.dumps(sector_rules) if sector_rules else None,
            created_by=get_jwt_identity(),
        )
        session.add(cfg)
        session.flush()
        result = cfg.to_dict()

    return jsonify(result), 201


@segmentation_configs.get("/<int:config_id>")
@require_perm("model_config:read")
def get_config(config_id):
    cfg = SegmentationConfig.query.filter_by(id=config_id).first()
    if not cfg:
        return jsonify({"error": "Not found"}), 404
    return jsonify(cfg.to_dict()), 200


@segmentation_configs.patch("/<int:config_id>")
@require_perm("model_config:write")
def update_config(config_id):
    body = request.get_json(silent=True) or {}

    with app_session() as session:
        cfg = SegmentationConfig.query.filter_by(id=config_id).first()
        if not cfg:
            return jsonify({"error": "Not found"}), 404

        if "name" in body:
            cfg.name = body["name"]
        if "description" in body:
            cfg.description = body.get("description") or None
        if "default_split" in body:
            if body["default_split"] not in ("subsector", "country"):
                return jsonify(
                    {"error": "default_split must be 'subsector' or 'country'"}
                ), 400
            cfg.default_split = body["default_split"]
        if "max_segments" in body:
            cfg.max_segments = int(body["max_segments"])
        if "sector_rules" in body:
            sector_rules = body["sector_rules"] or []
            for rule in sector_rules:
                if rule.get("split_by") not in ("subsector", "country"):
                    return jsonify(
                        {
                            "error": "sector_rules[].split_by must be 'subsector' or 'country'"
                        }
                    ), 400
            cfg.sector_rules_json = json.dumps(sector_rules) if sector_rules else None

        session.add(cfg)
        session.flush()
        result = cfg.to_dict()

    return jsonify(result), 200


@segmentation_configs.get("/<int:config_id>/refs")
@require_perm("model_config:read")
def get_refs(config_id):
    cfg = SegmentationConfig.query.filter_by(id=config_id).first()
    if not cfg:
        return jsonify({"error": "Not found"}), 404

    runs = CalibrationRun.query.filter_by(segmentation_config_id=config_id).all()
    return jsonify(
        {
            "calibration_runs": [
                {"id": r.id, "run_id": r.run_id, "status": r.status} for r in runs
            ]
        }
    ), 200


@segmentation_configs.delete("/<int:config_id>")
@require_perm("model_config:write")
def delete_config(config_id):
    cfg = SegmentationConfig.query.filter_by(id=config_id).first()
    if not cfg:
        return jsonify({"error": "Not found"}), 404

    refs = CalibrationRun.query.filter_by(segmentation_config_id=config_id).all()
    if refs:
        n = len(refs)
        return jsonify(
            {
                "error": f"Cannot delete: {n} calibration run{'s' if n != 1 else ''} reference this config",
                "deps": [{"id": r.id, "run_id": r.run_id} for r in refs],
            }
        ), 409

    with app_session() as session:
        cfg = session.merge(cfg)
        session.delete(cfg)

    return "", 204
