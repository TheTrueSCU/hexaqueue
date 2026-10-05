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
