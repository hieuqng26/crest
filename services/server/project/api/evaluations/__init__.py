from flask import Blueprint

evaluations = Blueprint('evaluations', __name__)

from . import routes  # noqa: F401, E402
