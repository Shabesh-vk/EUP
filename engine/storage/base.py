"""Storage abstraction interface.

Adheres to Integration Standard #7:
"Inputs accepted as an upload or a URL. Outputs saved to S3-compatible storage
(MinIO in the compose file is fine) and returned as download links."
"""

from abc import ABC, abstractmethod


class BaseStorage(ABC):
    """Abstract interface for local or S3-compatible object storage."""

    @abstractmethod
    def save_file(self, local_path: str, destination_name: str) -> str:
        """Uploads or stores a file and returns its download URL or reference."""
        pass

    @abstractmethod
    def fetch_file(self, source_url_or_key: str, target_local_path: str) -> str:
        """Downloads or copies a remote or local file into target_local_path."""
        pass
