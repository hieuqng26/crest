"""Credit-risk run launch orchestration (transport-agnostic)."""

import uuid
from datetime import datetime, timezone

from project import app_session
from project.constants import RunStatus
from project.db_models.calibration_models import Dataset
from project.db_models.credit_models import CreditRiskForecastInput, CreditRiskRun
from project.db_models.forecast_models import ForecastRun
from project.exceptions import BadRequestError, NotFoundError
from project.schemas.credit_risk import CreateCreditRiskRun
from project.workers.tasks import run_credit_analysis

_REQUIRED_SLOTS = {"total_assets", "short_term_debts", "long_term_debts"}


def create_run(payload: CreateCreditRiskRun, identity: str) -> dict:
    """Validate + create a CreditRiskRun (+ forecast-input FKs) and dispatch
    ``run_credit_analysis``. Raises ``NotFoundError`` (404) / ``BadRequestError`` (400).
    """
    ds = Dataset.query.get(payload.dataset_id)
    if not ds:
        raise NotFoundError("Dataset not found")

    fin_id = payload.financial_portfolio_dataset_id
    if fin_id:
        if not Dataset.query.get(fin_id):
            raise NotFoundError("Financial portfolio dataset not found")

    forecast_inputs = payload.cal_inputs or {}
    missing = _REQUIRED_SLOTS - {k for k, v in forecast_inputs.items() if v}
    if missing:
        raise BadRequestError(f"Missing required forecast inputs: {sorted(missing)}")

    # Resolve each slot's UUID to its forecast run — validates existence/success
    # and becomes the FK reference that blocks accidental deletion of the run.
    slot_to_forecast_run: dict[str, ForecastRun] = {}
    for slot, run_uuid in forecast_inputs.items():
        fr = ForecastRun.query.filter_by(run_id=run_uuid).first()
        if not fr or fr.status != RunStatus.SUCCESS:
            raise BadRequestError(
                f"Forecast run for '{slot}' not found or not successful"
            )
        slot_to_forecast_run[slot] = fr

    cr_run_id = str(uuid.uuid4())
    with app_session() as s:
        cr = CreditRiskRun(
            run_id=cr_run_id,
            dataset_id=payload.dataset_id,
            financial_portfolio_dataset_id=fin_id,
            is_active=False,
            exposure=payload.exposure,
            discount_rate=payload.discount_rate,
            lifetime_horizon=payload.lifetime_horizon,
            curve=payload.curve,
            status=RunStatus.QUEUED,
            triggered_by=identity,
            created_at=datetime.now(timezone.utc),
        )
        s.add(cr)
        s.flush()
        for slot, fr in slot_to_forecast_run.items():
            s.add(
                CreditRiskForecastInput(
                    credit_risk_run_id=cr.id,
                    forecast_run_id=fr.id,
                    forecast_run_uuid=fr.run_id,
                    slot=slot,
                )
            )
        s.flush()
        cr_dict = cr.to_dict()

    run_credit_analysis.delay(cr_run_id)
    return cr_dict
