"""Domain models for storage volumes and shared filesystem mounts.

Notes/Architectural Intent:
    Defines representations of shared persistent filesystems (NFS, Lustre, GPFS,
    AWS EFS, GCP Filestore, local POSIX shares) mounted into worker execution
    environments or containers, along with mount options and read-only flags.
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FilesystemType(StrEnum):
    """Supported distributed or local filesystem types.

    Notes/Architectural Intent:
        Covers high-performance parallel HPC storage (Lustre, GPFS), cloud network
        shares (AWS EFS, GCP Filestore), and standard POSIX/NFS exports.
    """

    AWS_EFS = "aws_efs"
    GCP_FILESTORE = "gcp_filestore"
    GPFS = "gpfs"
    LOCAL_POSIX = "local_posix"
    LUSTRE = "lustre"
    NFS = "nfs"


class SharedVolumeMount(BaseModel):
    """Specification of a shared volume mount into an execution environment.

    Args:
        name: Logical name identifying the shared mount volume.
        source_path: Host or network filesystem root path.
        mount_path: Destination directory path within container/execution sandbox.
        filesystem_type: Underlying storage engine type.
        read_only: Whether the volume is mounted read-only to avoid mutation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    filesystem_type: FilesystemType = Field(
        default=FilesystemType.LOCAL_POSIX,
        description="Type of underlying filesystem",
    )
    mount_path: str = Field(
        description="Destination path inside the compute environment"
    )
    name: str = Field(description="Logical name for the mount volume")
    read_only: bool = Field(default=False, description="Mount volume as read-only")
    source_path: str = Field(
        description="Source directory path on host or network share"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate non-empty paths and names."""
        if not self.name.strip():
            msg = "Mount name cannot be empty"
            raise ValueError(msg)
        if not self.source_path.strip():
            msg = "Mount source_path cannot be empty"
            raise ValueError(msg)
        if not self.mount_path.strip():
            msg = "Mount mount_path cannot be empty"
            raise ValueError(msg)
        return self


__all__ = [
    "FilesystemType",
    "SharedVolumeMount",
]
