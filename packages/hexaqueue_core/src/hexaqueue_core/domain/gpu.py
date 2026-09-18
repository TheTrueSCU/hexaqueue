"""GPU device and allocation domain models.

Notes/Architectural Intent:
    Represents hardware accelerators detected via NVML or platform queries, tracking
    device index, model name, total and free VRAM, and health status.
    Provides immutable GpuAllocation models that map assigned devices to jobs and
    format CUDA_VISIBLE_DEVICES strings for runtime process environment injection.
"""

from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GpuDevice(BaseModel):
    """Physical or virtual GPU accelerator device detected on compute node.

    Args:
        index: Zero-indexed physical GPU device ordinal.
        name: Hardware device product or architecture name.
        uuid: Globally unique device UUID (e.g. 'GPU-fa20...').
        total_vram_mb: Total onboard device memory in megabytes.
        free_vram_mb: Currently available unallocated memory in megabytes.
        is_healthy: Whether the device passes diagnostic health checks.
        temperature_c: Optional current core temperature in degrees Celsius.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    free_vram_mb: int = Field(ge=0, description="Free available memory in megabytes")
    index: int = Field(ge=0, description="Device ordinal index")
    is_healthy: bool = Field(
        default=True, description="Whether device is operating normally"
    )
    name: str = Field(description="GPU device model name")
    temperature_c: int | None = Field(
        default=None, description="Current temperature in Celsius"
    )
    total_vram_mb: int = Field(gt=0, description="Total VRAM in megabytes")
    uuid: str = Field(description="Unique device UUID")

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate GPU device constraints and consistency."""
        if not self.name.strip():
            msg = "GPU device name cannot be empty"
            raise ValueError(msg)
        if not self.uuid.strip():
            msg = "GPU UUID cannot be empty"
            raise ValueError(msg)
        if self.free_vram_mb > self.total_vram_mb:
            msg = (
                f"free_vram_mb ({self.free_vram_mb}) cannot exceed "
                f"total_vram_mb ({self.total_vram_mb})"
            )
            raise ValueError(msg)
        return self


class GpuAllocation(BaseModel):
    """Immutable record of physical GPU devices allocated to a running job.

    Args:
        job_id: The job identifier holding this GPU allocation.
        device_indices: List of assigned physical GPU device indices.
        allocated_at: Timestamp when allocation was granted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    allocated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of allocation",
    )
    device_indices: list[int] = Field(
        default_factory=list, description="Allocated device indices"
    )
    job_id: str = Field(description="Holding job identifier")

    @property
    def cuda_visible_devices_env(self) -> str:
        """Format assigned device indices as a standard CUDA_VISIBLE_DEVICES string.

        Returns:
            Comma-separated string of device ordinals, or empty string if no GPUs.
        """
        return ",".join(str(idx) for idx in sorted(self.device_indices))

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate allocation integrity and non-negative unique indices."""
        if not self.job_id.strip():
            msg = "job_id cannot be empty"
            raise ValueError(msg)
        for idx in self.device_indices:
            if idx < 0:
                msg = f"Device index cannot be negative, got {idx}"
                raise ValueError(msg)
        if len(self.device_indices) != len(set(self.device_indices)):
            msg = f"Duplicate device indices in allocation: {self.device_indices}"
            raise ValueError(msg)
        return self


__all__ = [
    "GpuAllocation",
    "GpuDevice",
]
