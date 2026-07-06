"""Shared helpers for routing a client (sector/subsector/country) to its trained
segment's forecast trajectory. Used by the credit-risk analysis Celery task and by
the read-only Heatmap / Financial Forecast endpoints — kept in one place so segment
resolution can't drift between the two call sites.
"""

import json

import pandas as pd

from project.db_models.forecast_models import ForecastRun, ForecastRunResult


def build_variable_index(forecast_run: ForecastRun) -> tuple[dict, dict]:
    """Build the segmentation info + prediction index for one successful ForecastRun.

    Returns (seg_info, idx_map) where:
      seg_info = {"split_by": {sector: 'subsector'|'country'},
                  "top_values": {sector: {trained split_value, ...}},
                  "fallback": {sector: any segment_key for that sector}}
      idx_map[segment_key_or_None][scenario][year] = predicted

    Raises ValueError if the run has no results.
    """
    from project.db_models.calibration_models import (
        CalibrationRun,
        CalibrationRunSegment,
    )

    fr_rows = (
        ForecastRunResult.query.filter_by(forecast_run_id=forecast_run.id)
        .order_by(ForecastRunResult.id)
        .all()
    )
    if not fr_rows:
        raise ValueError(f"Forecast run {forecast_run.run_id[:8]}… has no results")

    seg_info = {"split_by": {}, "top_values": {}, "fallback": {}}
    cal_run = CalibrationRun.query.get(forecast_run.calibration_run_id)
    if cal_run and cal_run.seg_sectors_json:
        cal_segments = CalibrationRunSegment.query.filter_by(
            calibration_run_id=cal_run.id, status="success"
        ).all()
        for s in cal_segments:
            seg_info["split_by"][s.sector] = s.split_by
            seg_info["top_values"].setdefault(s.sector, set()).add(s.split_value)
            seg_info["fallback"].setdefault(s.sector, s.segment_key)

    idx_map: dict[str | None, dict[str, dict[int, float]]] = {}
    for row in fr_rows:
        meta = json.loads(row.meta_json or "{}")
        ctx = meta.get("segment_key")
        scen = str(meta.get("scenario", "Baseline"))
        try:
            yr = int(pd.to_datetime(str(row.date)).year)
        except Exception:
            yr = int(str(row.date)[:4]) if row.date else 2024
        if row.predicted is not None:
            idx_map.setdefault(ctx, {}).setdefault(scen, {})[yr] = float(row.predicted)

    return seg_info, idx_map


def resolve_segment_key(
    seg_info: dict, sector: str, subsector: str, country: str
) -> str | None:
    split_by = seg_info["split_by"].get(sector)
    if not split_by:
        return None
    split_val = subsector if split_by == "subsector" else country
    top_vals = seg_info["top_values"].get(sector, set())
    if split_val in top_vals:
        return f"{sector}__{split_val}"
    if "Others" in top_vals:
        return f"{sector}__Others"
    return seg_info["fallback"].get(sector)


def lookup_forecast(
    seg_info: dict, idx_map: dict, sector: str, subsector: str, country: str
) -> dict:
    """Return {scenario: {year: value}} for the segment this client routes to."""
    if seg_info["split_by"]:
        target = resolve_segment_key(seg_info, sector, subsector, country)
        if target and target in idx_map:
            return idx_map[target]
    return idx_map.get(None, {})
