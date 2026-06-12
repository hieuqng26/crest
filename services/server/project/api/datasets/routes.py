import json
import io
import uuid
import pandas as pd
import pyodbc
from flask import jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
from project import db, app_session, DATA_STORE
from project.db_models.calibration_models import Dataset
from project.core import storage
from project.logger import get_logger
from . import datasets

logger = get_logger(__name__)

ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'parquet'}


def _ext(filename: str) -> str:
    return filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''


def _read_dataframe(file_bytes: bytes, ext: str) -> pd.DataFrame:
    buf = io.BytesIO(file_bytes)
    if ext == 'csv':
        return pd.read_csv(buf)
    if ext == 'xlsx':
        return pd.read_excel(buf)
    if ext == 'parquet':
        return pd.read_parquet(buf)
    raise ValueError(f"Unsupported file type: {ext}")


@datasets.get('/')
@jwt_required()
def list_datasets():
    rows = Dataset.query.filter(Dataset.status != 'deleted').order_by(Dataset.created_at.desc()).all()
    return jsonify([r.to_dict() for r in rows]), 200


@datasets.post('/upload')
@jwt_required()
def upload_dataset():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    f = request.files['file']
    ext = _ext(f.filename)
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': f'Unsupported file type .{ext}'}), 400

    name = request.form.get('name', f.filename)
    description = request.form.get('description', '')

    file_bytes = f.read()
    try:
        df = _read_dataframe(file_bytes, ext)
    except Exception as e:
        return jsonify({'error': f'Failed to parse file: {e}'}), 422

    object_name = f"uploads/{uuid.uuid4().hex}/{f.filename}"
    try:
        artifact_path = storage.upload_bytes(object_name, file_bytes)
    except Exception as e:
        logger.error(f"MinIO upload failed: {e}")
        return jsonify({'error': 'File storage unavailable'}), 503

    schema = json.dumps({'columns': list(df.columns), 'dtypes': {c: str(t) for c, t in df.dtypes.items()}})

    with app_session() as session:
        ds = Dataset(
            name=name,
            description=description,
            source='upload',
            file_path=artifact_path,
            schema_json=schema,
            row_count=len(df),
            created_by=get_jwt_identity(),
            status='ready'
        )
        session.add(ds)
        session.flush()
        result = ds.to_dict()

    return jsonify(result), 201


@datasets.post('/query')
@jwt_required()
def query_dataset():
    body = request.get_json(silent=True) or {}
    sql = body.get('sql', '').strip()
    name = body.get('name', f'query_{uuid.uuid4().hex[:8]}')

    if not sql:
        return jsonify({'error': 'sql is required'}), 400

    # Safety: read-only guard — reject anything that isn't a SELECT
    first_word = sql.split()[0].upper() if sql.split() else ''
    if first_word not in ('SELECT', 'WITH'):
        return jsonify({'error': 'Only SELECT / WITH queries are permitted'}), 400

    try:
        import os
        conn_str = os.getenv('RISK_DB_CONN_STR', '')
        if not conn_str:
            return jsonify({'error': 'Risk DB not configured'}), 503
        with pyodbc.connect(conn_str, timeout=30) as conn:
            df = pd.read_sql(sql, conn)
    except Exception as e:
        logger.error(f"Risk DB query failed: {e}")
        return jsonify({'error': f'Query failed: {e}'}), 422

    schema = json.dumps({'columns': list(df.columns), 'dtypes': {c: str(t) for c, t in df.dtypes.items()}})

    with app_session() as session:
        ds = Dataset(
            name=name,
            description=body.get('description', ''),
            source='live_query',
            file_path=None,
            schema_json=schema,
            row_count=len(df),
            created_by=get_jwt_identity(),
            status='ready'
        )
        session.add(ds)
        session.flush()
        result = ds.to_dict()

    return jsonify(result), 201


@datasets.get('/<int:dataset_id>')
@jwt_required()
def get_dataset(dataset_id):
    ds = Dataset.query.filter_by(id=dataset_id).first()
    if not ds or ds.status == 'deleted':
        return jsonify({'error': 'Not found'}), 404
    return jsonify(ds.to_dict()), 200


@datasets.delete('/<int:dataset_id>')
@jwt_required()
def delete_dataset(dataset_id):
    ds = Dataset.query.filter_by(id=dataset_id).first()
    if not ds or ds.status == 'deleted':
        return jsonify({'error': 'Not found'}), 404
    with app_session() as session:
        ds.status = 'deleted'
        session.add(ds)
    return jsonify({'deleted': dataset_id}), 200
