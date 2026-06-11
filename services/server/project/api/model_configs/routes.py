from flask import jsonify
from flask_jwt_extended import jwt_required
from . import model_configs


@model_configs.get('/registry')
@jwt_required()
def list_registry():
    return jsonify([]), 200


@model_configs.get('/')
@jwt_required()
def list_configs():
    return jsonify([]), 200


@model_configs.post('/')
@jwt_required()
def create_config():
    return jsonify({'error': 'Not implemented'}), 501


@model_configs.get('/<int:config_id>')
@jwt_required()
def get_config(config_id):
    return jsonify({'error': 'Not implemented'}), 501
