from flask import Blueprint

credit_risk = Blueprint('credit_risk', __name__)

from . import routes  # noqa: F401, E402
