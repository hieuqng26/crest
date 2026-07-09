"""Forecast-implied 1-year rating transition matrices.

Pure computation over KMV rating paths (no Flask/DB), so it is unit-testable by
file-path import like the rest of core/credit_risk. The KMV model assigns each
client a Rating per (year, scenario); counting Rating[t] -> Rating[t+1] across
all clients and row-normalising gives a genuine transition matrix. This is a
*forecast-implied* matrix (from model rating paths), NOT a historical/agency
cohort matrix — the platform has no observed rating-history data.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

# Canonical scenario ordering shared with the rest of the credit-risk UI
# (mirrors routes._all_scenarios / the frontend scenario order).
_SCENARIO_ORDER = {"Baseline": 0, "Adverse": 1, "Severely Adverse": 2}


def _ordered_scenarios(scenarios: Iterable[str]) -> list[str]:
    return sorted(set(scenarios), key=lambda s: (_SCENARIO_ORDER.get(s, 99), s))


def build_transition_matrices(
    client_kmv_rows: Iterable[list[dict]],
    rating_category: dict[str, int],
) -> dict:
    """See module docstring / plan interface for the return shape."""
    # scenario -> {(from, to): count}
    counts: dict[str, dict[tuple[str, str], int]] = defaultdict(
        lambda: defaultdict(int)
    )
    # scenario -> set of contributing client indices
    clients_seen: dict[str, set[int]] = defaultdict(set)
    # scenario -> [min_year, max_year] of rows used in a transition
    year_span: dict[str, list[int]] = {}

    for idx, kmv_rows in enumerate(client_kmv_rows):
        # Group this client's rows by scenario.
        by_scen: dict[str, list[dict]] = defaultdict(list)
        for row in kmv_rows or []:
            scen = row.get("SCENARIO")
            if scen is None:
                continue
            by_scen[str(scen)].append(row)

        for scen, rows in by_scen.items():
            ordered = sorted(rows, key=lambda r: r.get("YEAR", 0))
            if len(ordered) < 2:
                continue
            contributed = False
            for a, b in zip(ordered, ordered[1:]):
                fr, to = a.get("Rating"), b.get("Rating")
                ya, yb = a.get("YEAR"), b.get("YEAR")
                if fr is None or to is None or ya is None or yb is None:
                    continue
                if int(yb) - int(ya) != 1:
                    # Non-adjacent years (a client missing from some forecast time
                    # steps — see kmv.py) are not genuine 1-year transitions.
                    continue
                counts[scen][(str(fr), str(to))] += 1
                contributed = True
                for y in (a.get("YEAR"), b.get("YEAR")):
                    if y is None:
                        continue
                    span = year_span.get(scen)
                    if span is None:
                        year_span[scen] = [int(y), int(y)]
                    else:
                        span[0] = min(span[0], int(y))
                        span[1] = max(span[1], int(y))
            if contributed:
                clients_seen[scen].add(idx)

    scenarios = _ordered_scenarios(counts.keys())
    by_scenario: dict[str, dict] = {}
    _big = float("inf")

    for scen in scenarios:
        pair_counts = counts[scen]
        observed: set[str] = set()
        for fr, to in pair_counts:
            observed.add(fr)
            observed.add(to)
        ratings = sorted(observed, key=lambda r: (rating_category.get(r, _big), r))
        idx_of = {r: i for i, r in enumerate(ratings)}

        n = len(ratings)
        count_grid = [[0] * n for _ in range(n)]
        for (fr, to), c in pair_counts.items():
            count_grid[idx_of[fr]][idx_of[to]] = c

        row_totals = [sum(r) for r in count_grid]
        matrix = [
            [
                round(count_grid[i][j] / row_totals[i] * 100, 1)
                if row_totals[i]
                else 0.0
                for j in range(n)
            ]
            for i in range(n)
        ]

        by_scenario[scen] = {
            "ratings": ratings,
            "matrix": matrix,
            "counts": count_grid,
            "row_totals": row_totals,
            "n_transitions": sum(row_totals),
            "n_clients": len(clients_seen[scen]),
            "years": year_span.get(scen, []),
        }

    return {"scenarios": scenarios, "by_scenario": by_scenario}
