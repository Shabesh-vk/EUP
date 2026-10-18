"""S3 / MinIO compatible storage provider."""

from pathlib import Path
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from engine.storage.base import BaseStorage
from engine.storage.local import LocalStorage
from engine.config import settings
from engine.logging_config import logger


class S3MinIOStorage(BaseStorage):
    """Stores files in MinIO / Amazon S3 compatible object storage."""

    def __init__(
        self,
        endpoint_url: str = settings.S3_ENDPOINT_URL,
        access_key: str = settings.S3_ACCESS_KEY,
        secret_key: str = settings.S3_SECRET_KEY,
        bucket_name: str = settings.S3_BUCKET_NAME,
        region: str = settings.S3_REGION,
        secure: bool = settings.S3_SECURE
    ):
        self.bucket_name = bucket_name
        self.endpoint_url = endpoint_url

        self.s3_client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            use_ssl=secure
        )
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
        except ClientError:
            try:
                self.s3_client.create_bucket(Bucket=self.bucket_name)
            except Exception as e:
                logger.warning(f"Could not auto-create S3 bucket '{self.bucket_name}': {e}")

    def save_file(self, local_path: str, destination_name: str) -> str:
        path = Path(local_path).resolve()
        key = destination_name.lstrip("/")
        self.s3_client.upload_file(str(path), self.bucket_name, key)
        return f"{self.endpoint_url}/{self.bucket_name}/{key}"

    def fetch_file(self, source_url_or_key: str, target_local_path: str) -> str:
        tgt = Path(target_local_path).resolve()
        tgt.parent.mkdir(parents=True, exist_ok=True)

        if source_url_or_key.startswith("http"):
            key = source_url_or_key.split(f"/{self.bucket_name}/")[-1]
        else:
            key = source_url_or_key.lstrip("/")

        self.s3_client.download_file(self.bucket_name, key, str(tgt))
        return str(tgt)


def get_storage() -> BaseStorage:
    """Factory creating configured storage provider."""
    if settings.STORAGE_BACKEND == "s3":
        try:
            return S3MinIOStorage()
        except Exception as e:
            logger.warning(f"Failed to connect to S3/MinIO: {e}. Falling back to LocalStorage.")
            return LocalStorage()
    return LocalStorage()
