import json
import re
import uuid
from datetime import datetime, timezone

from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.orm import selectinload

from project import app_session, db
from project.api.auth.decorators import current_permissions, require_perm
from project.api.auth.permissions import has_permission
from project.core.calibration_launch import (
    build_search_config_json,
    validate_segmentation,
)
from project.db_models.calibration_models import CalibrationRun, Dataset, ModelConfig
from project.db_models.credit_models import (
    CreditRiskForecastInput,
    CreditRiskRun,
    CreditRiskRunLog,
)
from project.db_models.forecast_models import ForecastRun
from project.db_models.workflow_models import WorkflowRun
from project.workers.tasks import run_calibration

from . import workflows

_NUMERIC_DTYPE_PREFIXES = ("int", "float", "uint")


def _latest_dataset(kind: str) -> Dataset | None:
    return (
        Dataset.query.filter_by(kind=kind, status="ready")
        .order_by(Dataset.created_at.desc())
        .first()
    )


def _dataset_schema(ds: Dataset) -> tuple[set, dict]:
    schema = json.loads(ds.schema_json or "{}")
    return set(schema.get("columns", [])), schema.get("dtypes", {})


def _launch_workflow(
    name, resolved_targets, analysis_params, datasets, identity, parsed_seg=None
):
    """
    Creates a WorkflowRun + CalibrationRuns in the DB, dispatches run_calibration.delay
    for each, and returns (wf_dict, created_list).

    datasets = {
        'calibration': Dataset,
        'forecast': Dataset,
        'credit': Dataset | None,
        'financial': Dataset | None,
    }
    resolved_targets = [
        {'target_col': str, '_cfg': ModelConfig, 'feature_cols': list[str]}
    ]
    analysis_params = {'exposure': float, 'discount_rate': float,
                       'lifetime_horizon': int, 'curve': str}
    """
    if parsed_seg is None:
        parsed_seg = {
            "seg_sectors_json": None,
            "seg_split_by": None,
            "seg_max_segments": None,
            "seg_sector_overrides_json": None,
        }

    cal_ds = datasets["calibration"]
    fc_ds = datasets["forecast"]
    credit_ds = datasets.get("credit")
    fin_ds = datasets.get("financial")

    wf_run_id = str(uuid.uuid4())

    with app_session() as s:
        wf = WorkflowRun(
            run_id=wf_run_id,
            name=name,
            status="queued",
            current_stage="training",
            triggered_by=identity,
            created_at=datetime.now(timezone.utc),
            calibration_dataset_id=cal_ds.id,
            forecast_dataset_id=fc_ds.id,
            credit_dataset_id=credit_ds.id if credit_ds else None,
            financial_dataset_id=fin_ds.id if fin_ds else None,
            targets_json=json.dumps(
                [
                    {
                        "target_col": t["target_col"],
                        "model_config_id": t["_cfg"].id,
                        "feature_cols": t["feature_cols"],
                    }
                    for t in resolved_targets
                ]
            ),
            analysis_params_json=json.dumps(analysis_params),
        )
        s.add(wf)
        s.flush()

        created = []
        for t in resolved_targets:
            cfg = t["_cfg"]
            cal_run_id = str(uuid.uuid4())
            run = CalibrationRun(
                run_id=cal_run_id,
                name=f"{name} · {t['target_col']}",
                dataset_id=cal_ds.id,
                model_config_id=cfg.id,
                status="queued",
                triggered_by=identity,
                search_config_json=build_search_config_json(cfg),
                train_split=cfg.train_split if cfg.train_split is not None else 0.8,
                scaler=cfg.scaler,
                target_col=t["target_col"],
                feature_cols_json=json.dumps(t["feature_cols"]),
                seg_sectors_json=parsed_seg["seg_sectors_json"],
                seg_split_by=parsed_seg["seg_split_by"],
                seg_max_segments=parsed_seg["seg_max_segments"],
                seg_sector_overrides_json=parsed_seg["seg_sector_overrides_json"],
                workflow_run_id=wf.id,
            )
            s.add(run)
            s.flush()
            created.append(
                {"target_col": t["target_col"], "calibration_run_id": cal_run_id}
            )

        wf_dict = wf.to_dict()

    for c in created:
        # Dispatch after the session commits. If the session rolls back unexpectedly, these
        # tasks will reference non-existent rows — see .claude/bugs/detached-instance-in-celery-tasks.md
        run_calibration.delay(c["calibration_run_id"])

    return wf_dict, created


@workflows.get("/resolve-datasets")
@require_perm("calibration:read")
def resolve_datasets():
    result = {}
    for key in ("calibration", "forecast", "credit", "financial_portfolio"):
        ds = _latest_dataset(key)
        result[key] = ds.to_dict() if ds else None
    return jsonify(result), 200


@workflows.get("/")
@require_perm("calibration:read")
def list_workflows():
    """List workflows. Each workflow is one process with a single overall
    status — no per-stage (training/forecast/analysis) breakdown here; see
    GET /<run_id> for the per-target detail."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    paged = WorkflowRun.query.order_by(WorkflowRun.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    wf_ids = [wf.id for wf in paged.items]
    cr_by_wf = {}
    if wf_ids:
        for cr in CreditRiskRun.query.filter(
            CreditRiskRun.workflow_run_id.in_(wf_ids)
        ).all():
            cr_by_wf[cr.workflow_run_id] = cr

    result = []
    for wf in paged.items:
        d = wf.to_dict()
        cr = cr_by_wf.get(wf.id)
        d["analysis_summary"] = (
            {"run_id": cr.run_id, "is_active": bool(cr.is_active), "status": cr.status}
            if cr
            else None
        )
        result.append(d)
    return jsonify(
        {"items": result, "total": paged.total, "page": page, "pages": paged.pages}
    ), 200


@workflows.get("/<run_id>")
@require_perm("calibration:read")
def get_workflow(run_id):
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        return jsonify({"error": "Not found"}), 404

    cals = (
        CalibrationRun.query.options(selectinload(CalibrationRun.model_config))
        .filter_by(workflow_run_id=wf.id)
        .all()
    )
    fcs = ForecastRun.query.filter_by(workflow_run_id=wf.id).all()
    crs = CreditRiskRun.query.filter_by(workflow_run_id=wf.id).all()
    fcs_by_cal = {fr.calibration_run_id: fr for fr in fcs}
    cal_by_id = {cal.id: cal for cal in cals}

    # Batch-load every dataset referenced by the forecast runs and by the four
    # workflow dataset slots, so the per-target fr.to_dict() and the slot loop
    # below don't each fire their own .get() (was 3 queries/target + 4 slot gets).
    ds_ids = {fr.dataset_id for fr in fcs}
    ds_ids.update(
        i
        for i in (
            wf.calibration_dataset_id,
            wf.forecast_dataset_id,
            wf.credit_dataset_id,
            wf.financial_dataset_id,
        )
        if i
    )
    datasets = (
        {d.id: d for d in Dataset.query.filter(Dataset.id.in_(ds_ids))}
        if ds_ids
        else {}
    )

    targets = []
    for cal in cals:
        cal_d = cal.to_dict()
        cal_d["config_name"] = cal.model_config.name if cal.model_config else None
        cal_d["algorithm"] = cal.model_config.algorithm if cal.model_config else None
        fr = fcs_by_cal.get(cal.id)
        forecast_d = None
        if fr:
            fr_cal = cal_by_id.get(fr.calibration_run_id)
            fr_cfg = fr_cal.model_config if fr_cal else None
            forecast_d = fr.to_dict(
                cal_run=fr_cal,
                dataset=datasets.get(fr.dataset_id),
                config_name=fr_cfg.name if fr_cfg else None,
            )
        targets.append(
            {
                "target_col": cal.target_col,
                "calibration": cal_d,
                "forecast": forecast_d,
            }
        )

    d = wf.to_dict()
    d["targets"] = targets
    d["analysis"] = crs[0].to_dict() if crs else None
    for key, ds_id in (
        ("calibration_dataset_name", wf.calibration_dataset_id),
        ("forecast_dataset_name", wf.forecast_dataset_id),
        ("credit_dataset_name", wf.credit_dataset_id),
        ("financial_dataset_name", wf.financial_dataset_id),
    ):
        ds = datasets.get(ds_id) if ds_id else None
        d[key] = ds.name if ds else None
    return jsonify(d), 200


@workflows.post("/")
@require_perm("calibration:execute")
def create_workflow():
    perms = current_permissions()
    if not (
        has_permission(perms, "forecast:execute")
        and has_permission(perms, "credit_risk:execute")
    ):
        return jsonify(
            {
                "error": "Launching a workflow requires calibration, forecast and "
                "credit_risk execute permissions"
            }
        ), 403

    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    targets = body.get("targets") or []
    if not isinstance(targets, list) or not targets:
        return jsonify({"error": "targets must be a non-empty list"}), 400

    target_cols = []
    for i, t in enumerate(targets):
        if not isinstance(t, dict) or not t.get("target_col"):
            return jsonify({"error": f"targets[{i}].target_col is required"}), 400
        target_cols.append(t["target_col"])
    if len(set(target_cols)) != len(target_cols):
        return jsonify({"error": "targets must have unique target_col values"}), 400

    default_model_config_id = body.get("model_config_id")
    if not default_model_config_id:
        return jsonify({"error": "model_config_id is required"}), 400
    default_cfg = ModelConfig.query.get(int(default_model_config_id))
    if not default_cfg:
        return jsonify({"error": "ModelConfig not found"}), 404

    resolved_targets = []
    for t in targets:
        override_cfg_id = t.get("model_config_id")
        if override_cfg_id:
            cfg = ModelConfig.query.get(int(override_cfg_id))
            if not cfg:
                return jsonify(
                    {
                        "error": f"ModelConfig {override_cfg_id} not found for "
                        f"target '{t['target_col']}'"
                    }
                ), 404
        else:
            cfg = default_cfg
        resolved_targets.append(
            {
                "target_col": t["target_col"],
                "feature_cols": t.get("feature_cols") or None,
                "_cfg": cfg,
            }
        )

    seg = body.get("segmentation") or None
    parsed_seg, seg_error = validate_segmentation(seg)
    if seg_error:
        return jsonify({"error": seg_error}), 400

    cal_ds = _latest_dataset("calibration")
    if not cal_ds:
        return jsonify(
            {
                "error": "No calibration dataset uploaded yet — upload a dataset "
                "of kind 'calibration' first."
            }
        ), 422
    fc_ds = _latest_dataset("forecast")
    if not fc_ds:
        return jsonify(
            {
                "error": "No forecast dataset uploaded yet — upload a macro "
                "forecast dataset (kind 'forecast') first."
            }
        ), 422
    credit_ds = _latest_dataset("credit")
    fin_ds = _latest_dataset("financial_portfolio")

    cal_columns, cal_dtypes = _dataset_schema(cal_ds)
    fc_columns, _ = _dataset_schema(fc_ds)

    def _is_numeric(col: str) -> bool:
        return str(cal_dtypes.get(col, "")).startswith(_NUMERIC_DTYPE_PREFIXES)

    all_target_cols = set(target_cols)
    default_feature_cols = body.get("feature_cols") or None

    for t in resolved_targets:
        if t["target_col"] not in cal_columns:
            return jsonify(
                {
                    "error": f"target_col '{t['target_col']}' not found in the "
                    "calibration dataset"
                }
            ), 422
        if not _is_numeric(t["target_col"]):
            return jsonify(
                {
                    "error": f"target_col '{t['target_col']}' is not numeric in "
                    "the calibration dataset"
                }
            ), 422

    def _default_features_for(target_col: str) -> list:
        return sorted(
            c
            for c in cal_columns
            if _is_numeric(c) and c not in all_target_cols and c in fc_columns
        )

    for t in resolved_targets:
        feats = (
            t["feature_cols"]
            or default_feature_cols
            or _default_features_for(t["target_col"])
        )
        # Leakage guard: a target can never be used as a sibling's feature.
        feats = [f for f in feats if f not in all_target_cols]
        missing_in_forecast = sorted(set(feats) - fc_columns)
        if missing_in_forecast:
            return jsonify(
                {
                    "error": f"Feature column(s) {missing_in_forecast} for target "
                    f"'{t['target_col']}' are not present in the forecast dataset "
                    "— the forecast stage would fail. Remove them or pick "
                    "different features."
                }
            ), 422
        t["feature_cols"] = feats

    analysis_body = body.get("analysis") or {}
    analysis_params = {
        "exposure": float(analysis_body.get("exposure", 1_000_000)),
        "discount_rate": float(analysis_body.get("discount_rate", 0.05)),
        "lifetime_horizon": int(analysis_body.get("lifetime_horizon", 5)),
        "curve": analysis_body.get("curve", "moodys"),
    }

    datasets = {
        "calibration": cal_ds,
        "forecast": fc_ds,
        "credit": credit_ds,
        "financial": fin_ds,
    }
    wf_dict, created_list = _launch_workflow(
        name,
        resolved_targets,
        analysis_params,
        datasets,
        get_jwt_identity(),
        parsed_seg,
    )
    wf_dict["targets"] = created_list
    return jsonify(wf_dict), 202


@workflows.post("/<run_id>/cancel")
@require_perm("calibration:write")
def cancel_workflow(run_id):
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        return jsonify({"error": "Not found"}), 404
    if wf.status not in ("queued", "running"):
        return jsonify(
            {"error": f"Cannot cancel a workflow with status '{wf.status}'"}
        ), 409

    with app_session() as s:
        for cal in CalibrationRun.query.filter_by(workflow_run_id=wf.id).all():
            if cal.status in ("queued", "running"):
                cal.status = "failed"
                cal.finished_at = datetime.now(timezone.utc)
                cal.error_message = "Cancelled by user"
                s.add(cal)
        for fr in ForecastRun.query.filter_by(workflow_run_id=wf.id).all():
            if fr.status in ("queued", "running"):
                fr.status = "failed"
                fr.finished_at = datetime.now(timezone.utc)
                fr.error_message = "Cancelled by user"
                s.add(fr)
        for cr in CreditRiskRun.query.filter_by(workflow_run_id=wf.id).all():
            if cr.status in ("queued", "running"):
                cr.status = "failed"
                cr.finished_at = datetime.now(timezone.utc)
                cr.error_message = "Cancelled by user"
                s.add(cr)

        wf.status = "failed"
        wf.finished_at = datetime.now(timezone.utc)
        wf.error_message = "Cancelled by user"
        s.add(wf)
        result = wf.to_dict()

    return jsonify(result), 200


@workflows.post("/<run_id>/rerun")
@require_perm("calibration:execute")
def rerun_workflow(run_id):
    perms = current_permissions()
    if not (
        has_permission(perms, "forecast:execute")
        and has_permission(perms, "credit_risk:execute")
    ):
        return jsonify(
            {
                "error": "Launching a workflow requires calibration, forecast and "
                "credit_risk execute permissions"
            }
        ), 403

    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        return jsonify({"error": "Not found"}), 404

    if wf.status in ("queued", "running"):
        return jsonify(
            {"error": "Workflow is still active — cancel it before re-running"}
        ), 409

    targets_raw = json.loads(wf.targets_json or "[]")
    resolved_targets = []
    for t in targets_raw:
        cfg = db.session.get(ModelConfig, t["model_config_id"])
        if not cfg:
            return jsonify(
                {
                    "error": f"ModelConfig {t['model_config_id']} not found for "
                    f"target '{t['target_col']}' — configuration may have been deleted"
                }
            ), 422
        resolved_targets.append(
            {
                "target_col": t["target_col"],
                "feature_cols": t.get("feature_cols") or [],
                "_cfg": cfg,
            }
        )

    cal_ds = _latest_dataset("calibration")
    if not cal_ds:
        return jsonify(
            {
                "error": "No calibration dataset uploaded yet — upload a dataset "
                "of kind 'calibration' first."
            }
        ), 422
    fc_ds = _latest_dataset("forecast")
    if not fc_ds:
        return jsonify(
            {
                "error": "No forecast dataset uploaded yet — upload a macro "
                "forecast dataset (kind 'forecast') first."
            }
        ), 422
    credit_ds = _latest_dataset("credit")
    fin_ds = _latest_dataset("financial_portfolio")

    analysis_params = json.loads(wf.analysis_params_json or "{}")

    datasets = {
        "calibration": cal_ds,
        "forecast": fc_ds,
        "credit": credit_ds,
        "financial": fin_ds,
    }
    name = re.sub(r"( \(re-run\))+$", "", wf.name) + " (re-run)"
    wf_dict, created_list = _launch_workflow(
        name, resolved_targets, analysis_params, datasets, get_jwt_identity()
    )
    wf_dict["targets"] = created_list
    return jsonify(wf_dict), 202


@workflows.put("/<run_id>/activate")
@require_perm("credit_risk:write")
def activate_workflow(run_id):
    """Set the workflow's credit risk run as the active analysis run,
    deactivating all others. Returns 404 if the workflow has no credit run."""
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        return jsonify({"error": "Not found"}), 404

    cr = CreditRiskRun.query.filter_by(workflow_run_id=wf.id).first()
    if not cr:
        return jsonify({"error": "This workflow has no credit risk run"}), 404
    if cr.status != "success":
        return jsonify({"error": "Credit risk run has not completed successfully"}), 422

    cr_run_id = cr.run_id
    with app_session() as s:
        CreditRiskRun.query.update({CreditRiskRun.is_active: False})
        cr_obj = s.get(CreditRiskRun, cr.id)
        cr_obj.is_active = True
        s.add(cr_obj)

    return jsonify({"activated": cr_run_id}), 200


@workflows.delete("/<run_id>")
@require_perm("calibration:write")
def delete_workflow(run_id):
    wf = WorkflowRun.query.filter_by(run_id=run_id).first()
    if not wf:
        return jsonify({"error": "Not found"}), 404

    cals = CalibrationRun.query.filter_by(workflow_run_id=wf.id).all()
    fcs = ForecastRun.query.filter_by(workflow_run_id=wf.id).all()
    crs = CreditRiskRun.query.filter_by(workflow_run_id=wf.id).all()

    active = [r for r in (*cals, *fcs, *crs) if r.status in ("queued", "running")]
    if active:
        return jsonify(
            {"error": "Cannot delete a workflow with an active run — cancel it first"}
        ), 409

    fr_ids = [fr.id for fr in fcs]
    outside_refs = (
        CreditRiskForecastInput.query.filter(
            CreditRiskForecastInput.forecast_run_id.in_(fr_ids)
        ).all()
        if fr_ids
        else []
    )
    outside_cr_ids = {inp.credit_risk_run_id for inp in outside_refs} - {
        cr.id for cr in crs
    }
    if outside_cr_ids:
        return jsonify(
            {
                "error": "This workflow's forecast runs are referenced by credit "
                "risk job(s) outside this workflow. Delete those first."
            }
        ), 409

    with app_session() as s:
        for cr in crs:
            # CreditRiskRunLog FKs credit_risk_runs.run_id with no ORM cascade
            # relationship, so it must be cleared explicitly (results and
            # forecast inputs are cascade-deleted via their relationships).
            CreditRiskRunLog.query.filter_by(run_id=cr.run_id).delete()
            s.delete(CreditRiskRun.query.get(cr.id))
        for fr in fcs:
            s.delete(ForecastRun.query.get(fr.id))
        for cal in cals:
            s.delete(CalibrationRun.query.get(cal.id))
        s.delete(WorkflowRun.query.get(wf.id))

    return "", 204
