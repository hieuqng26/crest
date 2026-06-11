from flask import jsonify
from flask_jwt_extended import jwt_required
from . import credit_risk


@credit_risk.post('/ecl')
@jwt_required()
def compute_ecl():
    return jsonify({'error': 'Not implemented'}), 501


@credit_risk.post('/pd-lgd')
@jwt_required()
def compute_pd_lgd():
    return jsonify({'error': 'Not implemented'}), 501
