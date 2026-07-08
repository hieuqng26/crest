import io
import os

from minio import Minio
from minio.deleteobjects import DeleteObject
from minio.error import S3Error

from project.logger import get_logger

logger = get_logger(__name__)

_client: Minio | None = None


def get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            os.getenv("MINIO_ENDPOINT", "minio:9000"),
            access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
            secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
            secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
        )
        _ensure_bucket(_client)
    return _client


def _ensure_bucket(client: Minio) -> None:
    bucket = os.getenv("MINIO_BUCKET", "mst-artifacts")
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
    except S3Error as e:
        logger.error(f"MinIO bucket init error: {e}")


def upload_bytes(
    object_name: str, data: bytes, content_type: str = "application/octet-stream"
) -> str:
    bucket = os.getenv("MINIO_BUCKET", "mst-artifacts")
    client = get_client()
    client.put_object(
        bucket,
        object_name,
        io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )
    return f"{bucket}/{object_name}"


def download_bytes(object_name: str) -> bytes:
    bucket = os.getenv("MINIO_BUCKET", "mst-artifacts")
    client = get_client()
    response = client.get_object(bucket, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def upload_file(local_path: str, object_name: str) -> str:
    bucket = os.getenv("MINIO_BUCKET", "mst-artifacts")
    client = get_client()
    client.fput_object(bucket, object_name, local_path)
    return f"{bucket}/{object_name}"


def remove_object(object_name: str) -> None:
    """Remove a single object. Never raises — logs and swallows storage errors
    so callers (e.g. run deletion) are not blocked by MinIO hiccups; the DB is
    the source of truth."""
    bucket = os.getenv("MINIO_BUCKET", "mst-artifacts")
    try:
        get_client().remove_object(bucket, object_name)
    except Exception as e:  # noqa: BLE001 - best-effort cleanup
        logger.error(f"MinIO remove_object error for {object_name}: {e}")


def remove_prefix(prefix: str) -> None:
    """Recursively remove every object under a key prefix (e.g. all artifacts
    for a run under ``artifacts/{run_id}/``). Best-effort: logs per-object and
    fatal errors, never raises, so run deletion is never blocked by storage."""
    bucket = os.getenv("MINIO_BUCKET", "mst-artifacts")
    try:
        client = get_client()
        objects = client.list_objects(bucket, prefix=prefix, recursive=True)
        delete_list = (DeleteObject(obj.object_name) for obj in objects)
        for err in client.remove_objects(bucket, delete_list):
            logger.error(f"MinIO remove error under {prefix}: {err}")
    except Exception as e:  # noqa: BLE001 - best-effort cleanup
        logger.error(f"MinIO remove_prefix error for {prefix}: {e}")
