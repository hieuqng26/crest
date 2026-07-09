"""Characterization tests for the SerializerMixin migration.

Each asserts the mixin-generated to_dict() reproduces exactly what the former
hand-written to_dict returned — same keys, same values, datetimes ISO-formatted.

Run from services/server/:
    pytest tests/test_serializer_mixin.py -v
"""

from datetime import datetime, timezone


def test_dataset_to_dict_matches_legacy(app):
    from project.db_models.calibration_models import Dataset

    dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    ds = Dataset(
        id=7,
        name="cal",
        description="d",
        source="upload",
        file_path="uploads/x.csv",
        schema_json='{"columns": []}',
        row_count=10,
        created_by="u@x.io",
        created_at=dt,
        status="ready",
        kind="calibration",
    )
    assert ds.to_dict() == {
        "id": 7,
        "name": "cal",
        "description": "d",
        "source": "upload",
        "file_path": "uploads/x.csv",
        "schema_json": '{"columns": []}',
        "row_count": 10,
        "created_by": "u@x.io",
        "created_at": dt.isoformat(),
        "status": "ready",
        "kind": "calibration",
    }


def test_dataset_to_dict_null_datetime(app):
    from project.db_models.calibration_models import Dataset

    ds = Dataset(id=1, name="n", source="upload", created_at=None)
    d = ds.to_dict()
    assert d["created_at"] is None  # None stays None (not isoformatted)


def test_pd_rating_to_dict_matches_legacy(app):
    from project.db_models.credit_models import PdRating

    r = PdRating(id=3, curve_name="moodys", category=5, rating="Baa2", pd=0.012)
    assert r.to_dict() == {
        "id": 3,
        "curve_name": "moodys",
        "category": 5,
        "rating": "Baa2",
        "pd": 0.012,
    }


def test_credit_risk_run_log_to_dict_matches_legacy(app):
    from project.db_models.credit_models import CreditRiskRunLog

    log = CreditRiskRunLog(
        id=2,
        run_id="cr-1",
        t="2026-01-01 00:00:00",
        level="info",
        message="hi",
        sector="Tech",
        segment="Tech__Sub",
    )
    assert log.to_dict() == {
        "id": 2,
        "run_id": "cr-1",
        "t": "2026-01-01 00:00:00",
        "level": "info",
        "message": "hi",
        "sector": "Tech",
        "segment": "Tech__Sub",
    }


def test_forecast_run_log_to_dict_matches_legacy(app):
    from project.db_models.forecast_models import ForecastRunLog

    log = ForecastRunLog(
        id=4,
        run_id="fr-1",
        t="2026-01-01 00:00:00",
        level="warn",
        message="w",
        sector=None,
        segment=None,
    )
    assert log.to_dict() == {
        "id": 4,
        "run_id": "fr-1",
        "t": "2026-01-01 00:00:00",
        "level": "warn",
        "message": "w",
        "sector": None,
        "segment": None,
    }
