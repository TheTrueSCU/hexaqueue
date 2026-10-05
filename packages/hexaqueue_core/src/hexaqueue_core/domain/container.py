"""Domain entities and value objects for container execution.

Notes/Architectural Intent:
    Represents declarative specifications for isolated containerized job execution
    across rootless Podman and Apptainer runtimes.
"""

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContainerRuntimeType(StrEnum):
    """Supported container execution runtime engines."""

    APPTAINER = "apptainer"
    PODMAN = "podman"


class ContainerMount(BaseModel):
    """Specification of a host-to-container volume or directory mount.

    Args:
        source: Host filesystem path.
        target: Container filesystem target path.
        read_only: Whether the mount is read-only.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(min_length=1, description="Host directory path")
    target: str = Field(min_length=1, description="Container target path")
    read_only: bool = Field(default=False, description="Read-only mount flag")

    @model_validator(mode="after")
    def validate_paths(self) -> Self:
        """Validate mount paths."""
        if not self.source.strip():
            msg = "Mount source path cannot be empty"
            raise ValueError(msg)
        if not self.target.strip():
            msg = "Mount target path cannot be empty"
            raise ValueError(msg)
        return self


class ContainerSpec(BaseModel):
    """Specification of an isolated container environment for job execution.

    Args:
        image: Container image identifier, OCI registry URI, or SIF file path.
        runtime: Preferred container runtime engine (Podman or Apptainer).
        workdir: Working directory path inside the container.
        read_only_rootfs: Whether the container root filesystem is read-only.
        mounts: Additional host-to-container bind mounts.
        gpu_enabled: Whether to grant container access to allocated GPU devices.
        privileged: Whether privileged mode is requested (defaults to False for rootless).
        entrypoint: Optional container entrypoint override.
        extra_args: Optional CLI arguments passed directly to the container runtime.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    image: str = Field(min_length=1, description="Container image tag or SIF path")
    runtime: ContainerRuntimeType | None = Field(
        default=None, description="Preferred runtime engine"
    )
    workdir: str = Field(default="/workspace", description="Container workdir")
    read_only_rootfs: bool = Field(
        default=False, description="Enforce read-only rootfs"
    )
    mounts: list[ContainerMount] = Field(
        default_factory=list, description="Volume mounts"
    )
    gpu_enabled: bool = Field(
        default=False, description="Enable GPU device passthrough"
    )
    privileged: bool = Field(default=False, description="Privileged execution flag")
    entrypoint: list[str] | None = Field(
        default=None, description="Entrypoint override"
    )
    extra_args: list[str] = Field(
        default_factory=list, description="Additional runtime CLI arguments"
    )

    @model_validator(mode="after")
    def validate_image(self) -> Self:
        """Validate container image string."""
        if not self.image.strip():
            msg = "Container image cannot be empty"
            raise ValueError(msg)
        return self


__all__ = [
    "ContainerMount",
    "ContainerRuntimeType",
    "ContainerSpec",
]
