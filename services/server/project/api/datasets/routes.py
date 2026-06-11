from flask import jsonify
from flask_jwt_extended import jwt_required
from . import datasets


@datasets.get('/')
@jwt_required()
def list_datasets():
    return jsonify([]), 200


@datasets.post('/upload')
@jwt_required()
def upload_dataset():
    return jsonify({'error': 'Not implemented'}), 501


@datasets.post('/query')
@jwt_required()
def query_dataset():
    return jsonify({'error': 'Not implemented'}), 501


@datasets.get('/<int:dataset_id>')
@jwt_required()
def get_dataset(dataset_id):
    return jsonify({'error': 'Not implemented'}), 501


@datasets.delete('/<int:dataset_id>')
@jwt_required()
def delete_dataset(dataset_id):
    return jsonify({'error': 'Not implemented'}), 501
