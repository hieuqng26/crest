"""Shared helpers for launching a calibration run: hyperparameter-search
resolution and segmentation-body validation. Used by both the single-target
POST /api/calibrations/ endpoint and the multi-target POST /api/workflows/
launcher, kept in one place so the two launch paths can't drift apart.
"""

import json
import math

from project.db_models.calibration_models import ModelConfig


def expand_param_values(defn: dict) -> list:
    """Expand a frontend param-grid definition into a flat list of candidate values."""
    kind = defn.get("kind", "list")
    if kind == "list":
        raw = str(defn.get("values", ""))
        parts = [s.strip() for s in raw.split(",") if s.strip()]
        result = []
        for p in parts:
            try:
                result.append(int(p))
            except ValueError:
                try:
                    result.append(float(p))
                except ValueError:
                    if p.lower() == "true":
                        result.append(True)
                    elif p.lower() == "false":
                        result.append(False)
                    else:
                        result.append(p)
        return result
    lo = float(defn.get("min", 0))
    hi = float(defn.get("max", 1))
    n = max(2, min(50, int(defn.get("steps", 5))))
    if lo == hi or n < 2:
        return [lo]
    if kind == "logspace":
        if lo <= 0 or hi <= 0:
            return []
        a, b = math.log10(lo), math.log10(hi)
        return [round(10 ** (a + (b - a) * i / (n - 1)), 10) for i in range(n)]
    return [round(lo + (hi - lo) * i / (n - 1), 10) for i in range(n)]


def build_search_config_json(cfg: ModelConfig) -> str | None:
    """Build the resolved CV search config JSON from a ModelConfig's saved
    search settings, or None if search is disabled / has no enabled params."""
    raw_search = json.loads(cfg.search_config_json or "null")
    if not raw_search or raw_search.get("mode", "none") == "none":
        return None
    param_grid = {}
    for param_name, defn in (raw_search.get("paramGrid") or {}).items():
        if not defn or not defn.get("enabled"):
            continue
        values = expand_param_values(defn)
        if values:
            param_grid[param_name] = values
    if not param_grid:
        return None
    return json.dumps(
        {
            "type": raw_search.get("mode", "grid"),
            "param_grid": param_grid,
            "cv": int(raw_search.get("folds", 5)),
            "scoring": raw_search.get("scoring", "roc_auc"),
            "n_iter": int(raw_search.get("nIter", 20)),
        }
    )


def validate_segmentation(seg: dict | None) -> tuple[dict | None, str | None]:
    """Validate a `segmentation` request body.

    Returns (parsed, error) where parsed is
    {seg_sectors_json, seg_split_by, seg_max_segments, seg_sector_overrides_json}
    (all None if `seg` is falsy) and error is an error message string, or None
    on success. Caller is responsible for turning `error` into a 400 response.
    """
    if not seg:
        return {
            "seg_sectors_json": None,
            "seg_split_by": None,
            "seg_max_segments": None,
            "seg_sector_overrides_json": None,
        }, None

    sectors = seg.get("sectors") or []
    split_by = seg.get("split_by") or ""
    max_segs = seg.get("max_segments")
    if not sectors or not isinstance(sectors, list):
        return None, "segmentation.sectors must be a non-empty list"
    if split_by not in ("subsector", "country"):
        return None, "segmentation.split_by must be 'subsector' or 'country'"
    if not isinstance(max_segs, int) or not (2 <= max_segs <= 20):
        return None, "segmentation.max_segments must be an integer 2–20"

    sector_overrides = seg.get("sector_overrides") or {}
    if sector_overrides:
        if not isinstance(sector_overrides, dict):
            return None, "segmentation.sector_overrides must be an object"
        for sector_name, override in sector_overrides.items():
            if sector_name not in sectors:
                return None, (
                    f"segmentation.sector_overrides has an entry for "
                    f"'{sector_name}', which is not in segmentation.sectors"
                )
            if not isinstance(override, dict):
                return (
                    None,
                    f"segmentation.sector_overrides['{sector_name}'] must be an object",
                )
            if "split_by" in override and override["split_by"] not in (
                "subsector",
                "country",
            ):
                return None, (
                    f"segmentation.sector_overrides['{sector_name}'].split_by "
                    "must be 'subsector' or 'country'"
                )
            if "max_segments" in override and (
                not isinstance(override["max_segments"], int)
                or not (2 <= override["max_segments"] <= 20)
            ):
                return None, (
                    f"segmentation.sector_overrides['{sector_name}']"
                    ".max_segments must be an integer 2–20"
                )
            if "model_config_id" in override:
                model_cfg_id = override["model_config_id"]
                if not isinstance(model_cfg_id, int):
                    return None, (
                        f"segmentation.sector_overrides['{sector_name}']"
                        ".model_config_id must be an integer"
                    )
                if not ModelConfig.query.get(model_cfg_id):
                    return None, (
                        f"segmentation.sector_overrides['{sector_name}']"
                        f".model_config_id {model_cfg_id} not found"
                    )
            if "feature_cols" in override and not isinstance(
                override["feature_cols"], list
            ):
                return None, (
                    f"segmentation.sector_overrides['{sector_name}']"
                    ".feature_cols must be a list"
                )

    return {
        "seg_sectors_json": json.dumps(sectors),
        "seg_split_by": split_by,
        "seg_max_segments": max_segs,
        "seg_sector_overrides_json": json.dumps(sector_overrides)
        if sector_overrides
        else None,
    }, None
