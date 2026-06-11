from flask import Blueprint

forecasts = Blueprint('forecasts', __name__)

from . import routes  # noqa: F401, E402
