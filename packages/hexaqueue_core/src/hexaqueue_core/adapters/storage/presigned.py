"""Presigned object storage adapters for in-memory and local development environments.

Notes/Architectural Intent:
    Provides mock and local filesystem implementations of PresignedStoragePort
    enabling hermetic testing and development without live cloud provider (S3/GCS)
    dependencies while maintaining identical preauthenticated URL semantics.
"""

import json
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.ports.storage import PresignedStoragePort


class InMemoryPresignedStorageAdapter(PresignedStoragePort):
    """In-memory mock adapter for presigned object storage operations.

    Notes/Architectural Intent:
        Used primarily in unit and property tests. Simulates presigned PUT/GET URL
        vending and direct object storage payloads entirely in memory.
    """

    def __init__(self, endpoint_url: str = "https://storage.local") -> None:
        """Initialize in-memory presigned storage adapter.

        Args:
            endpoint_url: Base virtual endpoint URI for synthetic presigned URLs.
        """
        self._endpoint_url = endpoint_url.rstrip("/")
        self._objects: dict[str, bytes] = {}
        self._metadata: dict[str, dict[str, str]] = {}

    async def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str | None = None,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Generate a synthetic presigned upload URL for testing.

        Args:
            key: Target object key.
            content_type: Optional expected MIME type.
            expires_in_seconds: Expiration window in seconds.

        Returns:
            Preauthenticated virtual upload URL.

        Notes/Architectural Intent:
            Encodes the key and expiry parameters into the query string for test inspection.
        """
        clean_key = key.lstrip("/")
        params = {"expires": str(expires_in_seconds)}
        if content_type:
            params["content_type"] = content_type
        query = urllib.parse.urlencode(params)
        return f"{self._endpoint_url}/upload/{clean_key}?{query}"

    async def generate_presigned_download_url(
        self,
        key: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Generate a synthetic presigned download URL for testing.

        Args:
            key: Target object key.
            expires_in_seconds: Expiration window in seconds.

        Returns:
            Preauthenticated virtual download URL.

        Raises:
            HexaqueueError: If object is not present in memory.
        """
        clean_key = key.lstrip("/")
        if clean_key not in self._objects:
            msg = f"Object '{clean_key}' not found in in-memory storage"
            raise HexaqueueError(msg)
        params = {"expires": str(expires_in_seconds)}
        query = urllib.parse.urlencode(params)
        return f"{self._endpoint_url}/download/{clean_key}?{query}"

    async def object_exists(self, key: str) -> bool:
        """Check whether object exists in memory.

        Args:
            key: Object key to check.

        Returns:
            True if object is stored, False otherwise.
        """
        return key.lstrip("/") in self._objects

    async def get_object_metadata(self, key: str) -> dict[str, str]:
        """Retrieve stored metadata dictionary for an object.

        Args:
            key: Object key.

        Returns:
            Dictionary of string metadata key-value pairs.

        Raises:
            HexaqueueError: If object is not found.
        """
        clean_key = key.lstrip("/")
        if clean_key not in self._objects:
            msg = f"Object '{clean_key}' not found in in-memory storage"
            raise HexaqueueError(msg)
        return dict(self._metadata.get(clean_key, {}))

    async def delete_object(self, key: str) -> None:
        """Delete an object from in-memory storage.

        Args:
            key: Object key to delete.
        """
        clean_key = key.lstrip("/")
        self._objects.pop(clean_key, None)
        self._metadata.pop(clean_key, None)

    # Test helper methods
    def put_object(
        self,
        key: str,
        data: bytes,
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Directly store an object payload in memory for test setup.

        Args:
            key: Target object key.
            data: Binary payload bytes.
            metadata: Optional metadata dictionary.
        """
        clean_key = key.lstrip("/")
        self._objects[clean_key] = data
        if metadata:
            self._metadata[clean_key] = dict(metadata)

    def get_object(self, key: str) -> bytes:
        """Directly retrieve an object payload from memory.

        Args:
            key: Target object key.

        Returns:
            Binary payload bytes.

        Raises:
            HexaqueueError: If object is not found.
        """
        clean_key = key.lstrip("/")
        if clean_key not in self._objects:
            msg = f"Object '{clean_key}' not found in in-memory storage"
            raise HexaqueueError(msg)
        return self._objects[clean_key]


class LocalPresignedStorageAdapter(PresignedStoragePort):
    """Local filesystem-backed presigned storage adapter.

    Notes/Architectural Intent:
        Implements presigned storage on local POSIX filesystems by generating
        file:// URIs, with sidecar metadata JSON persistence for lifecycle tags.
    """

    def __init__(self, base_dir: str | Path | None = None) -> None:
        """Initialize local presigned storage adapter with base directory.

        Args:
            base_dir: Root storage directory (defaults to ~/.hexaqueue/storage).
        """
        self._base_dir = (
            Path(base_dir) if base_dir else Path.home() / ".hexaqueue" / "storage"
        )
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _get_path(self, key: str) -> Path:
        """Resolve safe local path for key without traversal.

        Args:
            key: Object key.

        Returns:
            Resolved local filesystem Path.

        Raises:
            HexaqueueError: If path traversal is detected.
        """
        clean_key = key.lstrip("/").replace("\\", "/")
        target_path = (self._base_dir / clean_key).resolve()
        if not str(target_path).startswith(str(self._base_dir.resolve())):
            msg = f"Path traversal detected in storage key: {key}"
            raise HexaqueueError(msg)
        return target_path

    async def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str | None = None,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Generate a local file:// upload URL and ensure destination parent exists.

        Args:
            key: Target object key.
            content_type: Optional expected MIME type.
            expires_in_seconds: Expiration lifetime in seconds.

        Returns:
            Local file URI string.
        """
        target = self._get_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target.as_uri()

    async def generate_presigned_download_url(
        self,
        key: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Generate a local file:// download URL.

        Args:
            key: Target object key.
            expires_in_seconds: Expiration lifetime in seconds.

        Returns:
            Local file URI string.

        Raises:
            HexaqueueError: If file does not exist locally.
        """
        target = self._get_path(key)
        if not target.is_file():
            msg = f"Object '{key}' not found at local storage path '{target}'"
            raise HexaqueueError(msg)
        return target.as_uri()

    async def object_exists(self, key: str) -> bool:
        """Check whether local storage file exists.

        Args:
            key: Target object key.

        Returns:
            True if file exists, False otherwise.
        """
        target = self._get_path(key)
        return target.is_file()

    async def get_object_metadata(self, key: str) -> dict[str, str]:
        """Retrieve stored metadata dictionary from sidecar JSON or file stats.

        Args:
            key: Target object key.

        Returns:
            Dictionary of string metadata pairs.

        Raises:
            HexaqueueError: If object does not exist.
        """
        target = self._get_path(key)
        if not target.is_file():
            msg = f"Object '{key}' not found"
            raise HexaqueueError(msg)

        meta_file = target.with_suffix(target.suffix + ".meta.json")
        if meta_file.is_file():
            try:
                return json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception as exc:
                msg = f"Failed to read metadata for object '{key}': {exc}"
                raise HexaqueueError(msg) from exc

        stat = target.stat()
        return {
            "size_bytes": str(stat.st_size),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        }

    async def delete_object(self, key: str) -> None:
        """Delete local storage file and its sidecar metadata.

        Args:
            key: Target object key to delete.
        """
        target = self._get_path(key)
        if target.is_file():
            target.unlink()
        meta_file = target.with_suffix(target.suffix + ".meta.json")
        if meta_file.is_file():
            meta_file.unlink()


__all__ = [
    "InMemoryPresignedStorageAdapter",
    "LocalPresignedStorageAdapter",
]
