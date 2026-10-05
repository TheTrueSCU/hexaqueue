"""Compute resource requirements and hardware specifications.

Notes/Architectural Intent:
    Defines resource requests, hardware accelerators, memory, scratch quotas,
    and walltime limits. Validates positive bounds and valid GPU architectures.
"""

from pydantic import BaseModel, ConfigDict, Field


class ResourceRequirements(BaseModel):
    """Resource specification for scheduling and node placement.

    Args:
        cpus: Number of CPU cores requested (minimum 1).
        ram_mb: Memory requested in Megabytes (minimum 128 MB).
        gpus: Number of GPU accelerators requested (0 for CPU-only).
        gpu_model: Optional specific GPU model architecture (e.g. 'h100', 'a100', 'l4', 't4').
        vram_mb: Optional minimum VRAM per GPU in Megabytes.
        scratch_mb: Minimum local NVMe scratch disk space in Megabytes.
        walltime_seconds: Maximum execution time ceiling before automated SIGKILL (minimum 10s).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cpus: int = Field(default=1, ge=1, description="CPU cores requested")
    ram_mb: int = Field(default=1024, ge=128, description="Memory requested in MB")
    gpus: int = Field(default=0, ge=0, description="Number of GPUs requested")
    gpu_model: str | None = Field(default=None, description="Target GPU model")
    vram_mb: int | None = Field(
        default=None, ge=0, description="Minimum VRAM per GPU in MB"
    )
    scratch_mb: int = Field(default=1024, ge=0, description="Scratch disk in MB")
    walltime_seconds: int = Field(
        default=3600, ge=10, description="Max walltime in seconds"
    )
