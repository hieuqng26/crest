"""Credit-risk analysis read models — heatmap & forecast payload builders.

Pure computation over an already-loaded materialised *series* structure (the
route/tool loads it from the DB/cache and passes it in). No Flask, no ORM here,
so the MCP analysis-read tools call these directly. Errors are ``DomainError``s.

The ``series`` structure is:
    {scope_type: {scope_key: {slot: {scenario: {year: value}}}}}
where ``scenario`` includes the reserved ``SERIES_HISTORY`` key for actuals.
"""

from project.exceptions import (
    BadRequestError,
    NotFoundError,
    UnprocessableEntityError,
)

SERIES_HISTORY = "History"

_SCENARIO_ORDER = {"Baseline": 0, "Adverse": 1, "Severely Adverse": 2}

# Heatmap metric catalogue: label/unit for display + the forecast slots each
# metric needs present on the run.
HEATMAP_METRICS = {
    "revenue_growth": {
        "label": "Revenue growth",
        "unit": "% YoY",
        "needs": {"total_revenue"},
    },
    "cogs_margin": {
        "label": "COGS / Revenue",
        "unit": "Δ pp",
        "needs": {"total_revenue", "total_cogs"},
    },
    "leverage": {
        "label": "Net debt / EBITDA",
        "unit": "Δ turns",
        "needs": {"total_revenue", "total_cogs", "short_term_debts", "long_term_debts"},
    },
}

# Canonical forecast target slots (key, display title), in display order.
FORECAST_TARGET_SLOTS: list[tuple[str, str]] = [
    ("total_assets", "Total Assets"),
    ("short_term_debts", "Short-term Debts"),
    ("long_term_debts", "Long-term Debts"),
    ("total_revenue", "Revenue"),
    ("total_cogs", "COGS"),
]


def series_levels(series, scope_type, scope_key, slot, scenario) -> dict:
    """One ``{year: value}`` level series from the loaded structure."""
    return series.get(scope_type, {}).get(scope_key, {}).get(slot, {}).get(scenario, {})


def series_scenarios(series: dict) -> list[str]:
    """Non-history scenarios present, in Baseline → Adverse → Severely Adverse order."""
    scens: set[str] = set()
    for scope_map in series.values():
        for key_map in scope_map.values():
            for slot_map in key_map.values():
                scens.update(slot_map.keys())
    scens.discard(SERIES_HISTORY)
    return sorted(scens, key=lambda s: (_SCENARIO_ORDER.get(s, 99), s))


def forecast_years(series: dict, scenario: str = "Baseline") -> list[int]:
    """Forecast years for ``scenario`` present anywhere in the series."""
    return sorted(
        {
            yr
            for scope_map in series.values()
            for key_map in scope_map.values()
            for slot_map in key_map.values()
            for yr in slot_map.get(scenario, {})
        }
    )


def _resolve_scenario(series: dict, requested_scenario: str | None) -> tuple[str, list]:
    scenarios = series_scenarios(series)
    if requested_scenario and requested_scenario not in scenarios:
        raise BadRequestError(f"Unknown scenario '{requested_scenario}'")
    scenario = requested_scenario or (
        "Baseline"
        if "Baseline" in scenarios
        else (scenarios[0] if scenarios else "Baseline")
    )
    return scenario, scenarios


def build_heatmap(
    series: dict,
    sector_of: dict,
    slots,
    *,
    metric: str,
    sector_filter: str | None,
    client_filter: set | None,
    requested_scenario: str | None,
) -> dict:
    """Build the sector/company heatmap payload for one metric + scenario.

    Raises ``BadRequestError`` (unknown metric/scenario),
    ``UnprocessableEntityError`` (metric needs an unlinked forecast slot),
    ``NotFoundError`` (sector/company not present).
    """
    if metric not in HEATMAP_METRICS:
        raise BadRequestError(f"Unknown metric '{metric}'")
    spec = HEATMAP_METRICS[metric]

    missing = spec["needs"] - set(slots)
    if missing:
        raise UnprocessableEntityError(
            f"This metric needs forecast inputs for: {', '.join(sorted(missing))}. "
            "Link them on the active analysis run."
        )

    scenario, scenarios = _resolve_scenario(series, requested_scenario)
    years = forecast_years(series, scenario)

    def combined_levels(scope_type, scope_key, slot) -> dict:
        levels = dict(
            series_levels(series, scope_type, scope_key, slot, SERIES_HISTORY)
        )
        levels.update(series_levels(series, scope_type, scope_key, slot, scenario))
        return levels

    def metric_series(scope_type, scope_key) -> dict:
        rev = combined_levels(scope_type, scope_key, "total_revenue")
        cogs = combined_levels(scope_type, scope_key, "total_cogs")
        st = combined_levels(scope_type, scope_key, "short_term_debts")
        lt = combined_levels(scope_type, scope_key, "long_term_debts")

        if metric == "revenue_growth":
            return rev
        if metric == "cogs_margin":
            yrs = sorted(set(rev) & set(cogs))
            return {y: (cogs[y] / rev[y] * 100) for y in yrs if rev[y]}
        # leverage
        yrs = sorted(set(rev) & set(cogs) & set(st) & set(lt))
        out = {}
        for y in yrs:
            ebitda = rev[y] - cogs[y]
            if ebitda:
                out[y] = (st[y] + lt[y]) / ebitda
        return out

    def yoy_deltas(level_series: dict, target_years: list[int]) -> list:
        all_years = sorted(level_series.keys())
        out = []
        for y in target_years:
            prior = [yy for yy in all_years if yy < y]
            if y not in level_series or not prior:
                out.append(None)
                continue
            prev_v, cur_v = level_series[prior[-1]], level_series[y]
            if metric == "revenue_growth":
                out.append(
                    round((cur_v - prev_v) / prev_v * 100, 1) if prev_v else None
                )
            else:
                out.append(round(cur_v - prev_v, 1))
        return out

    if sector_filter:
        sector_clients = sorted(
            cid for cid, sec in sector_of.items() if sec == sector_filter
        )
        if not sector_clients:
            raise NotFoundError(f"Sector '{sector_filter}' not found")
        if client_filter is not None:
            sector_clients = [c for c in sector_clients if c in client_filter]
            if not sector_clients:
                raise NotFoundError("None of the selected companies are in this sector")
        rows_out = [
            {
                "key": cid,
                "label": cid,
                "drillable": False,
                "values": yoy_deltas(metric_series("client", cid), years),
            }
            for cid in sector_clients
        ]
        return {
            "metric": metric,
            "label": spec["label"],
            "unit": spec["unit"],
            "years": years,
            "drilled": True,
            "title": sector_filter,
            "subtitle": f"Company-level {spec['label'].lower()} across forecast years",
            "scenario": scenario,
            "scenarios": scenarios,
            "rows": rows_out,
        }

    sectors = sorted(series.get("sector", {}).keys())
    rows_out = [
        {
            "key": sec,
            "label": sec,
            "drillable": True,
            "values": yoy_deltas(metric_series("sector", sec), years),
        }
        for sec in sectors
    ]
    return {
        "metric": metric,
        "label": spec["label"],
        "unit": spec["unit"],
        "years": years,
        "drilled": False,
        "title": "Sector Heatmap",
        "subtitle": "Forecasted change by sector and year",
        "scenario": scenario,
        "scenarios": scenarios,
        "rows": rows_out,
    }


def build_forecast(
    series: dict,
    slots,
    *,
    sector: str,
    client_id: str | None,
    requested_keys: set | None,
    indexed: bool,
) -> dict:
    """Build the per-target forecast series payload for a sector or one company.

    Raises ``NotFoundError`` if the requested scope has no rows.
    """
    scope_type, scope_key = ("client", client_id) if client_id else ("sector", sector)
    if scope_key not in series.get(scope_type, {}):
        raise NotFoundError("No matching clients found")

    def series_points(levels: dict) -> list[dict]:
        return [{"year": y, "value": round(levels[y], 4)} for y in sorted(levels)]

    def scenarios_for(slot_key: str) -> list[str]:
        present = set(
            series.get(scope_type, {}).get(scope_key, {}).get(slot_key, {}).keys()
        )
        present.discard(SERIES_HISTORY)
        return sorted(present, key=lambda s: (_SCENARIO_ORDER.get(s, 99), s))

    metrics_out = []
    for slot_key, title in FORECAST_TARGET_SLOTS:
        if slot_key not in slots:
            continue
        if requested_keys is not None and slot_key not in requested_keys:
            continue

        hist = series_levels(series, scope_type, scope_key, slot_key, SERIES_HISTORY)
        base_year = min(hist) if hist else None
        base_val = hist.get(base_year) if base_year is not None else None

        def to_series(levels: dict, base_val=base_val) -> list[dict]:
            if not indexed or not base_val:
                return series_points(levels)
            return [
                {"year": y, "value": round(levels[y] / base_val * 100, 2)}
                for y in sorted(levels)
            ]

        history_points = to_series(hist)
        scenarios_out = {
            scen: to_series(
                series_levels(series, scope_type, scope_key, slot_key, scen)
            )
            for scen in scenarios_for(slot_key)
        }
        baseline_pts = scenarios_out.get("Baseline", [])
        metrics_out.append(
            {
                "key": slot_key,
                "title": title,
                "unit": (
                    f"Indexed · {base_year} = 100" if indexed and base_year else "Level"
                ),
                "indexed": bool(indexed and base_val),
                "available": True,
                "history": history_points,
                "scenarios": scenarios_out,
                "value": baseline_pts[-1]["value"] if baseline_pts else None,
                "delta_pct": (
                    round(
                        (baseline_pts[-1]["value"] - history_points[-1]["value"])
                        / history_points[-1]["value"]
                        * 100,
                        1,
                    )
                    if baseline_pts and history_points and history_points[-1]["value"]
                    else None
                ),
                "base_year": base_year,
            }
        )

    return {"sector": sector, "client_id": client_id, "metrics": metrics_out}
