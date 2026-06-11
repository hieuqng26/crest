from flask import jsonify
from flask_jwt_extended import jwt_required
from . import calibrations


@calibrations.get('/')
@jwt_required()
def list_runs():
    return jsonify([]), 200


@calibrations.post('/')
@jwt_required()
def create_run():
    return jsonify({'error': 'Not implemented'}), 501


@calibrations.get('/<run_id>')
@jwt_required()
def get_run(run_id):
    return jsonify({'error': 'Not implemented'}), 501


@calibrations.get('/<run_id>/diagnostics')
@jwt_required()
def get_diagnostics(run_id):
    return jsonify({'error': 'Not implemented'}), 501


@calibrations.get('/<run_id>/forecast')
@jwt_required()
def get_forecast(run_id):
    return jsonify({'error': 'Not implemented'}), 501


@calibrations.post('/<run_id>/recalibrate')
@jwt_required()
def recalibrate(run_id):
    return jsonify({'error': 'Not implemented'}), 501
