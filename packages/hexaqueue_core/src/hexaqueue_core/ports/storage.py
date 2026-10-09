"""Storage volume and scratch filesystem port interfaces.

Notes/Architectural Intent:
    Defines abstract contracts for allocating, attaching, and reclaiming scratch
    storage and shared volumes. Supports both Software-Managed (POSIX local scratch,
    NFS, Ceph) and Provider-Native Deference (No-Op bypass for K8s CSI / Cloud EFS).
"""

from abc import ABC, abstractmethod
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VolumeAllocation(BaseModel):
    """Metadata describing an allocated storage volume.

    Args:
        volume_id: Unique identifier of the allocated volume.
        mount_path: Absolute or container-relative mount path.
        size_mb: Allocated capacity in megabytes.
        is_ephemeral: True if storage should be wiped on job termination.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_ephemeral: bool = Field(
        default=True, description="Whether storage is wiped on termination"
    )
    mount_path: str = Field(description="Target mount path for compute process")
    size_mb: int = Field(gt=0, description="Allocated storage capacity in megabytes")
    volume_id: str = Field(description="Unique storage volume identifier")

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate volume allocation invariants."""
        if not self.volume_id.strip():
            msg = "volume_id cannot be empty"
            raise ValueError(msg)
        if not self.mount_path.strip():
            msg = "mount_path cannot be empty"
            raise ValueError(msg)
        return self


class StorageVolumePort(ABC):
    """Abstract port interface for scratch storage and volume management.

    Notes/Architectural Intent:
        Implementations isolate file systems per job execution, avoiding
        cross-job pollution and enforcing scratch capacity quotas.
    """

    @abstractmethod
    async def allocate_scratch(
        self, job_id: str, size_mb: int, base_dir: str | None = None
    ) -> VolumeAllocation:
        """Allocate an isolated scratch storage volume for a job.

        Args:
            job_id: Unique job identifier.
            size_mb: Required scratch capacity in megabytes.
            base_dir: Optional base path override for local allocations.

        Returns:
            VolumeAllocation containing path and identifier details.

        Raises:
            HexaqueueError: If volume allocation or quota provisioning fails.
        """

    @abstractmethod
    async def cleanup_scratch(self, volume_id: str) -> None:
        """Clean up and reclaim scratch storage volume.

        Args:
            volume_id: Unique volume identifier to reclaim.

        Raises:
            HexaqueueError: If storage reclamation fails.
        """


class PresignedStoragePort(ABC):
    """Abstract port interface for presigned cloud and local object storage.

    Notes/Architectural Intent:
        Eliminates API server data transfer bottlenecks by allowing compute workers
        and clients to upload and download heavy payloads (collateral bundles, logs,
        container images) directly to/from S3, GCS, Azure Blob, or local object
        stores using time-bounded preauthenticated URLs.
    """

    @abstractmethod
    async def generate_presigned_upload_url(
        self,
        key: str,
        content_type: str | None = None,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Generate a time-bounded presigned PUT URL for direct object upload.

        Args:
            key: Target object key or storage path.
            content_type: Optional expected MIME type.
            expires_in_seconds: Expiration lifetime in seconds (default 1 hour).

        Returns:
            Preauthenticated upload URL string.

        Raises:
            HexaqueueError: If presigned URL generation fails.
        """

    @abstractmethod
    async def generate_presigned_download_url(
        self,
        key: str,
        expires_in_seconds: int = 3600,
    ) -> str:
        """Generate a time-bounded presigned GET URL for direct object download.

        Args:
            key: Object key to download.
            expires_in_seconds: Expiration lifetime in seconds (default 1 hour).

        Returns:
            Preauthenticated download URL string.

        Raises:
            HexaqueueError: If object is not found or URL generation fails.
        """

    @abstractmethod
    async def object_exists(self, key: str) -> bool:
        """Check whether an object exists in storage.

        Args:
            key: Object key to check.

        Returns:
            True if the object exists, False otherwise.
        """

    @abstractmethod
    async def get_object_metadata(self, key: str) -> dict[str, str]:
        """Retrieve metadata tags and headers for an object.

        Args:
            key: Object key.

        Returns:
            Dictionary of string key-value metadata pairs.

        Raises:
            HexaqueueError: If object is not found or metadata retrieval fails.
        """

    @abstractmethod
    async def delete_object(self, key: str) -> None:
        """Delete an object from storage.

        Args:
            key: Object key to delete.

        Raises:
            HexaqueueError: If object deletion encounters a transport error.
        """


__all__ = [
    "PresignedStoragePort",
    "StorageVolumePort",
    "VolumeAllocation",
]
