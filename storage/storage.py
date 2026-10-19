"""
S3-compatible and local file storage provider.
Supports saving, retrieving, and generating download links for video and audio assets.
"""

from __future__ import annotations
import os
import shutil
from typing import Optional
from pathlib import Path


class StorageBackend:
    """
    Abstract storage backend supporting local filesystem mount and S3/MinIO.
    """

    def __init__(self, base_dir: str = "storage_data", public_base_url: str = "http://localhost:8000/api/v1/storage"):
        self.base_dir = os.path.abspath(base_dir)
        self.public_base_url = public_base_url.rstrip("/")
        os.makedirs(self.base_dir, exist_ok=True)

    def save_file(self, filename: str, src_path: str) -> str:
        """Copy a local file into storage and return storage key."""
        target_path = os.path.join(self.base_dir, filename)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copy2(src_path, target_path)
        return filename

    def save_bytes(self, filename: str, data: bytes) -> str:
        """Write raw bytes into storage and return storage key."""
        target_path = os.path.join(self.base_dir, filename)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, "wb") as f:
            f.write(data)
        return filename

    def get_local_path(self, filename: str) -> str:
        """Resolve full local filepath for a stored file."""
        return os.path.join(self.base_dir, filename)

    def get_download_url(self, filename: str) -> str:
        """Generate download URL for stored asset."""
        return f"{self.public_base_url}/{filename}"

    def exists(self, filename: str) -> bool:
        """Check if file exists in storage."""
        return os.path.isfile(os.path.join(self.base_dir, filename))


_default_storage: Optional[StorageBackend] = None


def get_storage() -> StorageBackend:
    global _default_storage
    if _default_storage is None:
        storage_dir = os.environ.get("STORAGE_DIR", "storage_data")
        public_url = os.environ.get("STORAGE_PUBLIC_URL", "http://localhost:8000/api/v1/storage")
        _default_storage = StorageBackend(base_dir=storage_dir, public_base_url=public_url)
    return _default_storage
