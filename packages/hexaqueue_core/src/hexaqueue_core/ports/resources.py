"""Compute resource port interface for node discovery and capacity querying.

Notes/Architectural Intent:
    Provides hardware topology discovery (CPU cores, RAM capacity, GPU architectures via NVML),
    and current node resource utilization metrics.
"""

from abc import ABC, abstractmethod
from typing import Self
from pydantic import BaseModel, ConfigDict, Field, model_validator


class NodeCapacity(BaseModel):
    """Total capacity and available resources of a compute node.

    Args:
        node_id: Unique compute node identifier.
        total_cpus: Total CPU cores available.
        total_ram_mb: Total system memory in megabytes.
        total_gpus: Total physical GPUs detected.
        available_cpus: Free CPU cores available for allocation.
        available_ram_mb: Free system memory available for allocation.
        available_gpus: Free GPUs available for allocation.
        gpu_model: Optional detected GPU device model name (e.g. 'NVIDIA A100-SXM4-80GB').
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    available_cpus: int = Field(ge=0, description="Available free CPU cores")
    available_gpus: int = Field(default=0, ge=0, description="Available free GPUs")
    available_ram_mb: int = Field(ge=0, description="Available free RAM in megabytes")
    gpu_model: str | None = Field(default=None, description="GPU device model name")
    node_id: str = Field(description="Unique compute node identifier")
    total_cpus: int = Field(gt=0, description="Total physical/logical CPU cores")
    total_gpus: int = Field(default=0, ge=0, description="Total physical GPUs detected")
    total_ram_mb: int = Field(gt=0, description="Total memory in megabytes")

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate capacity invariants."""
        if not self.node_id.strip():
            msg = "node_id cannot be empty"
            raise ValueError(msg)
        if self.available_cpus > self.total_cpus:
            msg = f"available_cpus ({self.available_cpus}) exceeds total_cpus ({self.total_cpus})"
            raise ValueError(msg)
        if self.available_ram_mb > self.total_ram_mb:
            msg = f"available_ram_mb ({self.available_ram_mb}) exceeds total_ram_mb ({self.total_ram_mb})"
            raise ValueError(msg)
        if self.available_gpus > self.total_gpus:
            msg = f"available_gpus ({self.available_gpus}) exceeds total_gpus ({self.total_gpus})"
            raise ValueError(msg)
        return self


class ComputeResourcePort(ABC):
    """Abstract port interface for node capacity and resource discovery."""

    @abstractmethod
    async def get_node_capacity(self) -> NodeCapacity:
        """Query current compute node hardware capacity and free resources.

        Returns:
            NodeCapacity summarizing total and currently available resources.
        """
