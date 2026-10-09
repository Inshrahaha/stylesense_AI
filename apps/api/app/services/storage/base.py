"""
Storage service — base interface + LocalFS implementation.

Provider pattern: S3 for production/dev (MinIO), LocalFS for tests.
"""

import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import get_settings
from app.core.logging import get_logger

logger = get_logger("storage")


class StorageBase(ABC):
    """Abstract base class for object storage."""

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Store an object. Returns the key."""
        ...

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Retrieve an object by key."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete an object by key."""
        ...

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Check if an object exists."""
        ...

    @abstractmethod
    async def get_presigned_url(self, key: str, expires_in: int = 300) -> str:
        """Get a presigned URL for temporary access (max 5 min)."""
        ...

    def generate_key(self, user_id: uuid.UUID, kind: str) -> str:
        """Generate a random object key: u/{user_id}/{kind}/{uuid4}."""
        return f"u/{user_id}/{kind}/{uuid.uuid4()}"


class LocalFSStorage(StorageBase):
    """Local filesystem storage for tests and development."""

    def __init__(self, base_path: str | None = None):
        settings = get_settings()
        self.base_path = Path(base_path or settings.local_storage_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _full_path(self, key: str) -> Path:
        path = self.base_path / key
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        path = self._full_path(key)
        path.write_bytes(data)
        logger.debug(f"LocalFS: stored {len(data)} bytes at {key}")
        return key

    async def get(self, key: str) -> bytes:
        path = self._full_path(key)
        if not path.exists():
            raise FileNotFoundError(f"Object not found: {key}")
        return path.read_bytes()

    async def delete(self, key: str) -> None:
        path = self._full_path(key)
        if path.exists():
            path.unlink()
            logger.debug(f"LocalFS: deleted {key}")

    async def exists(self, key: str) -> bool:
        return self._full_path(key).exists()

    async def get_presigned_url(self, key: str, expires_in: int = 300) -> str:
        # LocalFS doesn't support presigned URLs; return a file:// path
        return f"file://{self._full_path(key).absolute()}"


def get_storage() -> StorageBase:
    """Factory for storage provider based on config."""
    settings = get_settings()
    if settings.storage_provider == "localfs":
        return LocalFSStorage()
    elif settings.storage_provider == "s3":
        from app.services.storage.s3 import S3Storage
        return S3Storage()
    else:
        raise ValueError(f"Unknown storage provider: {settings.storage_provider}")
