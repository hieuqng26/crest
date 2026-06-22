import io
import json
import uuid

import pandas as pd
import pyodbc
from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity

from project import app_session
from project.api.auth.decorators import require_perm
from project.core import storage
from project.db_models.calibration_models import Dataset
from project.logger import get_logger

from . import datasets

logger = get_logger(__name__)

ALLOWED_EXTENSIONS = {"csv", "xlsx", "parquet"}


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _read_dataframe(file_bytes: bytes, ext: str) -> pd.DataFrame:
    buf = io.BytesIO(file_bytes)
    if ext == "csv":
        return pd.read_csv(buf)
    if ext == "xlsx":
        return pd.read_excel(buf)
    if ext == "parquet":
        return pd.read_parquet(buf)
    raise ValueError(f"Unsupported file type: {ext}")


@datasets.get("/")
@require_perm("dataset:read")
def list_datasets():
    kind = request.args.get("kind")
    q = Dataset.query.filter(Dataset.status != "deleted")
    if kind:
        q = q.filter(Dataset.kind == kind)
    rows = q.order_by(Dataset.created_at.desc()).all()
    return jsonify([r.to_dict() for r in rows]), 200


@datasets.post("/upload")
@require_perm("dataset:write")
def upload_dataset():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    f = request.files["file"]
    ext = _ext(f.filename)
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Unsupported file type .{ext}"}), 400

    name = request.form.get("name", f.filename)
    description = request.form.get("description", "")
    kind = request.form.get("kind", "calibration")

    file_bytes = f.read()
    try:
        df = _read_dataframe(file_bytes, ext)
    except Exception as e:
        return jsonify({"error": f"Failed to parse file: {e}"}), 422

    object_name = f"uploads/{uuid.uuid4().hex}/{f.filename}"
    try:
        artifact_path = storage.upload_bytes(object_name, file_bytes)
    except Exception as e:
        logger.error(f"MinIO upload failed: {e}")
        return jsonify({"error": "File storage unavailable"}), 503

    schema = json.dumps(
        {
            "columns": list(df.columns),
            "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        }
    )

    with app_session() as session:
        ds = Dataset(
            name=name,
            description=description,
            source="upload",
            file_path=artifact_path,
            schema_json=schema,
            row_count=len(df),
            created_by=get_jwt_identity(),
            status="ready",
            kind=kind,
        )
        session.add(ds)
        session.flush()
        result = ds.to_dict()

    return jsonify(result), 201


@datasets.post("/query")
@require_perm("dataset:write")
def query_dataset():
    body = request.get_json(silent=True) or {}
    sql = body.get("sql", "").strip()
    name = body.get("name", f"query_{uuid.uuid4().hex[:8]}")

    if not sql:
        return jsonify({"error": "sql is required"}), 400

    # Safety: read-only guard — reject anything that isn't a SELECT
    first_word = sql.split()[0].upper() if sql.split() else ""
    if first_word not in ("SELECT", "WITH"):
        return jsonify({"error": "Only SELECT / WITH queries are permitted"}), 400

    try:
        import os

        conn_str = os.getenv("RISK_DB_CONN_STR", "")
        if not conn_str:
            return jsonify({"error": "Risk DB not configured"}), 503
        with pyodbc.connect(conn_str, timeout=30) as conn:
            df = pd.read_sql(sql, conn)
    except Exception as e:
        logger.error(f"Risk DB query failed: {e}")
        return jsonify({"error": f"Query failed: {e}"}), 422

    schema = json.dumps(
        {
            "columns": list(df.columns),
            "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        }
    )

    with app_session() as session:
        ds = Dataset(
            name=name,
            description=body.get("description", ""),
            source="live_query",
            file_path=None,
            schema_json=schema,
            row_count=len(df),
            created_by=get_jwt_identity(),
            status="ready",
        )
        session.add(ds)
        session.flush()
        result = ds.to_dict()

    return jsonify(result), 201


@datasets.get("/<int:dataset_id>/rows")
@require_perm("dataset:read")
def get_dataset_rows(dataset_id):
    ds = Dataset.query.filter_by(id=dataset_id).first()
    if not ds or ds.status == "deleted":
        return jsonify({"error": "Not found"}), 404
    if not ds.file_path:
        return jsonify({"rows": [], "total": 0}), 200

    try:
        object_name = ds.file_path.split("/", 1)[-1]
        file_bytes = storage.download_bytes(object_name)
        ext = object_name.rsplit(".", 1)[-1].lower()
        df = _read_dataframe(file_bytes, ext)
    except Exception as e:
        logger.error(f"Failed to load dataset {dataset_id}: {e}")
        return jsonify({"error": f"Could not load file: {e}"}), 500

    total = len(df)

    # Filter
    q = request.args.get("filter", "").strip()
    if q:
        mask = df.apply(
            lambda row: row.astype(str).str.contains(q, case=False).any(), axis=1
        )
        df = df[mask]

    # Sort
    sort_col = request.args.get("sort")
    sort_order = request.args.get("order", "asc")
    if sort_col and sort_col in df.columns:
        df = df.sort_values(sort_col, ascending=(sort_order == "asc"))

    # Paginate
    offset = max(0, int(request.args.get("offset", 0)))
    limit = min(500, max(1, int(request.args.get("limit", 50))))
    page = df.iloc[offset : offset + limit]

    rows = page.where(pd.notnull(page), None).to_dict(orient="records")
    return jsonify({"rows": rows, "total": total}), 200


@datasets.get("/<int:dataset_id>")
@require_perm("dataset:read")
def get_dataset(dataset_id):
    ds = Dataset.query.filter_by(id=dataset_id).first()
    if not ds or ds.status == "deleted":
        return jsonify({"error": "Not found"}), 404
    return jsonify(ds.to_dict()), 200


@datasets.delete("/<int:dataset_id>")
@require_perm("dataset:write")
def delete_dataset(dataset_id):
    ds = Dataset.query.filter_by(id=dataset_id).first()
    if not ds or ds.status == "deleted":
        return jsonify({"error": "Not found"}), 404
    with app_session() as session:
        ds.status = "deleted"
        session.add(ds)
    return jsonify({"deleted": dataset_id}), 200


@datasets.post("/bulk-delete")
@require_perm("dataset:write")
def bulk_delete_datasets():
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    if not ids:
        return jsonify({"error": "ids is required"}), 400
    deleted = 0
    for did in ids:
        ds = Dataset.query.filter_by(id=did).first()
        if not ds or ds.status == "deleted":
            continue
        with app_session() as session:
            ds.status = "deleted"
            session.add(ds)
        deleted += 1
    return jsonify({"deleted": deleted}), 200
