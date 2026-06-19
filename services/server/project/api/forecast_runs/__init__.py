from flask import Blueprint

forecast_runs = Blueprint("forecast_runs", __name__)

from project.api.forecast_runs import routes  # noqa: E402, F401
