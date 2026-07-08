"""Pure unit tests for the forecast-implied rating transition matrix.

Imported by file path (bypassing project/__init__.py, which pulls Flask) — same
pattern as tests/test_credit_risk.py.
"""

import importlib.util
import os
import sys

import pytest


def _import_module(name: str, rel_path: str):
    abs_path = os.path.join(os.path.dirname(__file__), "..", rel_path)
    spec = importlib.util.spec_from_file_location(name, abs_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_mod = _import_module("transitions", "project/core/credit_risk/transitions.py")
build_transition_matrices = _mod.build_transition_matrices

# Category ordering (best -> worst) for the ratings used below.
_CATEGORY = {"Baa1": 10, "Baa2": 11, "Baa3": 12, "Ba1": 13, "Ba2": 14}


def _client(scenario, path):
    """One client's KMV rows: path is [(year, rating), ...] for `scenario`."""
    return [{"YEAR": y, "SCENARIO": scenario, "Rating": r} for y, r in path]


def test_basic_two_clients_rows_normalise_to_100():
    clients = [
        _client("Baseline", [(2024, "Baa1"), (2025, "Baa1"), (2026, "Baa2")]),
        _client("Baseline", [(2024, "Baa1"), (2025, "Baa2"), (2026, "Baa2")]),
    ]
    out = build_transition_matrices(clients, _CATEGORY)

    assert out["scenarios"] == ["Baseline"]
    data = out["by_scenario"]["Baseline"]
    # Observed notches ordered best->worst.
    assert data["ratings"] == ["Baa1", "Baa2"]
    # From Baa1: 3 transitions (Baa1->Baa1, Baa1->Baa2, Baa1->Baa2) => 33.3 / 66.7
    baa1_row = data["matrix"][0]
    assert baa1_row == [pytest.approx(33.3, abs=0.05), pytest.approx(66.7, abs=0.05)]
    assert sum(baa1_row) == pytest.approx(100.0, abs=0.2)
    assert data["counts"][0] == [1, 2]
    assert data["row_totals"][0] == 3
    # From Baa2: only Baa2->Baa2 (client 1 year 2025->2026).
    assert data["counts"][1] == [0, 1]
    assert data["n_transitions"] == 4
    assert data["n_clients"] == 2
    assert data["years"] == [2024, 2026]


def test_single_year_client_is_skipped():
    clients = [
        _client("Baseline", [(2024, "Baa1")]),  # no next year -> no transition
        _client("Baseline", [(2024, "Baa2"), (2025, "Baa2")]),
    ]
    out = build_transition_matrices(clients, _CATEGORY)
    data = out["by_scenario"]["Baseline"]
    assert data["ratings"] == ["Baa2"]
    assert data["n_transitions"] == 1
    assert data["n_clients"] == 1


def test_destination_only_rating_appears_with_zero_row():
    # Ba1 only ever appears as a destination (terminal year) -> zero source row.
    clients = [_client("Baseline", [(2024, "Baa3"), (2025, "Ba1")])]
    out = build_transition_matrices(clients, _CATEGORY)
    data = out["by_scenario"]["Baseline"]
    assert data["ratings"] == ["Baa3", "Ba1"]  # ordered by category
    assert data["matrix"][0] == [pytest.approx(0.0), pytest.approx(100.0)]
    assert data["row_totals"] == [1, 0]  # Ba1 has no outgoing obs
    assert data["matrix"][1] == [0.0, 0.0]


def test_scenarios_separated_and_ordered():
    # One client carrying two scenarios; each scenario is tallied independently.
    mixed = [
        {"YEAR": 2024, "SCENARIO": "Baseline", "Rating": "Baa1"},
        {"YEAR": 2025, "SCENARIO": "Baseline", "Rating": "Baa2"},
        {"YEAR": 2024, "SCENARIO": "Adverse", "Rating": "Baa1"},
        {"YEAR": 2025, "SCENARIO": "Adverse", "Rating": "Ba1"},
    ]
    out = build_transition_matrices([mixed], _CATEGORY)
    # Canonical order: Baseline, Adverse, (Severely Adverse) ...
    assert out["scenarios"] == ["Baseline", "Adverse"]
    assert out["by_scenario"]["Adverse"]["ratings"] == ["Baa1", "Ba1"]
