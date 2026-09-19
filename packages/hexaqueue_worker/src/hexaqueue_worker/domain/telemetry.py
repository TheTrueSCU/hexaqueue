"""Domain models for worker and node telemetry pulses.

Notes/Architectural Intent:
    Defines immutable data structures representing point-in-time hardware resource
    utilization (CPU, memory, disk, NVML/GPU) and compute worker status.
"""

from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GpuTelemetry(BaseModel):
    """Point-in-time telemetry metrics for a GPU accelerator.

    Args:
        index: Zero-indexed GPU device index.
        model: Hardware device name (e.g. 'NVIDIA A100-SXM4-80GB').
        utilization_pct: GPU compute utilization percentage (0.0 to 100.0).
        vram_used_mb: VRAM memory used in megabytes.
        vram_total_mb: Total VRAM memory available in megabytes.
        temperature_c: GPU core temperature in Celsius.
        power_w: Current power draw in Watts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int = Field(ge=0, description="Device index")
    model: str = Field(description="GPU hardware model identifier")
    power_w: float = Field(
        default=0.0, ge=0.0, description="Power consumption in Watts"
    )
    temperature_c: float = Field(default=0.0, description="Core temperature in Celsius")
    utilization_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Compute utilization percentage",
    )
    vram_total_mb: int = Field(ge=0, description="Total VRAM in MB")
    vram_used_mb: int = Field(default=0, ge=0, description="Used VRAM in MB")


class NodeTelemetryPulse(BaseModel):
    """Periodic hardware telemetry pulse emitted by a worker compute node.

    Args:
        worker_id: Unique worker node identifier.
        timestamp: Pulse emission timestamp in UTC.
        cpu_utilization_pct: CPU core utilization percentage (0.0 to 100.0).
        load_average: 1-minute, 5-minute, and 15-minute system load averages.
        memory_used_mb: System RAM currently utilized in MB.
        memory_total_mb: Total system RAM in MB.
        scratch_used_mb: Scratch disk volume space consumed in MB.
        scratch_total_mb: Total scratch disk volume space in MB.
        active_jobs: Count of concurrently executing jobs on this worker.
        gpu_metrics: List of GpuTelemetry instances for attached accelerators.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_jobs: int = Field(default=0, ge=0, description="Active running jobs count")
    cpu_utilization_pct: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="CPU utilization percentage",
    )
    gpu_metrics: list[GpuTelemetry] = Field(
        default_factory=list, description="Attached GPU accelerator telemetry"
    )
    load_average: tuple[float, float, float] = Field(
        default=(0.0, 0.0, 0.0), description="Load averages (1m, 5m, 15m)"
    )
    memory_total_mb: int = Field(gt=0, description="Total physical RAM in MB")
    memory_used_mb: int = Field(ge=0, description="Used physical RAM in MB")
    scratch_total_mb: int = Field(gt=0, description="Total scratch disk capacity in MB")
    scratch_used_mb: int = Field(ge=0, description="Used scratch disk space in MB")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Pulse emission timestamp",
    )
    worker_id: str = Field(description="Unique worker node identifier")

    @property
    def memory_utilization_pct(self) -> float:
        """Percentage of RAM utilized."""
        return round((self.memory_used_mb / self.memory_total_mb) * 100.0, 2)

    @property
    def scratch_utilization_pct(self) -> float:
        """Percentage of scratch disk utilized."""
        return round((self.scratch_used_mb / self.scratch_total_mb) * 100.0, 2)

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate invariant constraints."""
        if not self.worker_id.strip():
            msg = "worker_id cannot be empty"
            raise ValueError(msg)
        return self


__all__ = [
    "GpuTelemetry",
    "NodeTelemetryPulse",
]
