import io
import os
from minio import Minio
from minio.error import S3Error
from project.logger import get_logger

logger = get_logger(__name__)

_client: Minio | None = None


def get_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            os.getenv('MINIO_ENDPOINT', 'minio:9000'),
            access_key=os.getenv('MINIO_ACCESS_KEY', 'minioadmin'),
            secret_key=os.getenv('MINIO_SECRET_KEY', 'minioadmin'),
            secure=os.getenv('MINIO_SECURE', 'false').lower() == 'true',
        )
        _ensure_bucket(_client)
    return _client


def _ensure_bucket(client: Minio) -> None:
    bucket = os.getenv('MINIO_BUCKET', 'mst-artifacts')
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
    except S3Error as e:
        logger.error(f"MinIO bucket init error: {e}")


def upload_bytes(object_name: str, data: bytes, content_type: str = 'application/octet-stream') -> str:
    bucket = os.getenv('MINIO_BUCKET', 'mst-artifacts')
    client = get_client()
    client.put_object(bucket, object_name, io.BytesIO(data), length=len(data), content_type=content_type)
    return f"{bucket}/{object_name}"


def download_bytes(object_name: str) -> bytes:
    bucket = os.getenv('MINIO_BUCKET', 'mst-artifacts')
    client = get_client()
    response = client.get_object(bucket, object_name)
    try:
        return response.read()
    finally:
        response.close()
        response.release_conn()


def upload_file(local_path: str, object_name: str) -> str:
    bucket = os.getenv('MINIO_BUCKET', 'mst-artifacts')
    client = get_client()
    client.fput_object(bucket, object_name, local_path)
    return f"{bucket}/{object_name}"
