from flask import jsonify
from flask_jwt_extended import jwt_required
from . import evaluations


@evaluations.get('/<run_id>')
@jwt_required()
def get_evaluation(run_id):
    return jsonify({'error': 'Not implemented'}), 501
