"""Local filesystem storage provider."""

import shutil
from pathlib import Path
from engine.storage.base import BaseStorage
from engine.config import settings


class LocalStorage(BaseStorage):
    """Stores files on the local filesystem."""

    def __init__(self, base_dir: str = settings.STORAGE_LOCAL_DIR):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save_file(self, local_path: str, destination_name: str) -> str:
        src = Path(local_path).resolve()
        dst = self.base_dir / destination_name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src != dst:
            shutil.copy2(src, dst)
        return f"/api/v1/storage/download/{destination_name}"

    def fetch_file(self, source_url_or_key: str, target_local_path: str) -> str:
        tgt = Path(target_local_path).resolve()
        tgt.parent.mkdir(parents=True, exist_ok=True)

        if source_url_or_key.startswith("http://") or source_url_or_key.startswith("https://"):
            import httpx
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(source_url_or_key)
                resp.raise_for_status()
                tgt.write_bytes(resp.content)
            return str(tgt)

        # Local file path or relative key
        key = source_url_or_key.replace("/api/v1/storage/download/", "").lstrip("/")
        local_src = self.base_dir / key
        if local_src.exists():
            shutil.copy2(local_src, tgt)
        elif Path(source_url_or_key).exists():
            shutil.copy2(Path(source_url_or_key), tgt)
        else:
            raise FileNotFoundError(f"Source file not found: {source_url_or_key}")

        return str(tgt)
