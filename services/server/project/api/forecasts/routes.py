from flask import jsonify
from flask_jwt_extended import jwt_required
from . import forecasts


@forecasts.get('/<run_id>')
@jwt_required()
def get_forecast(run_id):
    return jsonify({'error': 'Not implemented'}), 501
