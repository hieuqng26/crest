"""Dataset file loading — download from MinIO + parse into a DataFrame.

Consolidates the download-and-parse logic that was copy-pasted across the
datasets route, the credit-risk route, and the calibration/forecast Celery
tasks. Caching stays a caller concern (routes wrap these with the app cache /
request-scoped ``g``); these functions always do the real I/O.
"""

import io

import pandas as pd

from project.core import storage

_SUPPORTED_EXTENSIONS = ("csv", "xlsx", "parquet")


def read_dataframe(file_bytes: bytes, ext: str) -> pd.DataFrame:
    """Parse raw file bytes into a DataFrame by extension (csv/xlsx/parquet)."""
    buf = io.BytesIO(file_bytes)
    ext = ext.lower()
    if ext == "csv":
        return pd.read_csv(buf)
    if ext == "xlsx":
        return pd.read_excel(buf)
    if ext == "parquet":
        return pd.read_parquet(buf)
    raise ValueError(f"Unsupported file type: {ext}")


def _object_name(file_path: str) -> str:
    # file_path is stored as "<bucket-or-prefix>/<object-name>"; the object key
    # for MinIO is everything after the first slash.
    return file_path.split("/", 1)[-1]


def download_dataset_df(dataset) -> pd.DataFrame:
    """Download a ``Dataset``'s file from MinIO and parse it.

    ``dataset`` must have a truthy ``file_path``; callers that accept an id
    should use :func:`load_dataset_df_by_id`.
    """
    if not getattr(dataset, "file_path", None):
        raise ValueError(f"Dataset {getattr(dataset, 'id', '?')} has no file")
    object_name = _object_name(dataset.file_path)
    file_bytes = storage.download_bytes(object_name)
    ext = object_name.rsplit(".", 1)[-1]
    return read_dataframe(file_bytes, ext)


def load_dataset_df_by_id(dataset_id: int) -> pd.DataFrame:
    """Resolve a ``Dataset`` by primary key, then download + parse its file."""
    from project.db_models.calibration_models import Dataset

    dataset = Dataset.query.get(dataset_id)
    if not dataset or not dataset.file_path:
        raise ValueError(f"Dataset {dataset_id} not found or has no file")
    return download_dataset_df(dataset)
