"""Compute node GPU hardware discovery and allocation port interface.

Notes/Architectural Intent:
    Defines the contract for hardware accelerators, NVML device inspection, dynamic
    per-job GPU allocation, and process environment isolation (CUDA_VISIBLE_DEVICES).
    Prevents cross-job accelerator collisions by maintaining atomic ownership of
    physical GPU indices during job execution lifecycles.
"""

from abc import ABC, abstractmethod

from hexaqueue_core.domain.gpu import GpuAllocation, GpuDevice


class GpuDeviceManagerPort(ABC):
    """Abstract port interface for compute node GPU hardware management."""

    @abstractmethod
    async def enumerate_devices(self) -> list[GpuDevice]:
        """Query host or platform to discover all available physical/virtual GPU devices.

        Returns:
            List of GpuDevice instances describing detected accelerators.

        Raises:
            HexaqueueError: If hardware enumeration or driver communication fails.
        """

    @abstractmethod
    async def allocate_gpus(
        self,
        job_id: str,
        count: int,
        model: str | None = None,
        min_vram_mb: int | None = None,
    ) -> GpuAllocation:
        """Reserve a dedicated set of physical GPU indices for a job.

        Args:
            job_id: Unique job identifier requesting accelerator capacity.
            count: Number of discrete GPUs required.
            model: Optional architecture/model substring filter (e.g. 'A100').
            min_vram_mb: Optional minimum VRAM per allocated device in megabytes.

        Returns:
            GpuAllocation containing assigned device indices and CUDA environment variable.

        Raises:
            GpuAllocationError: If insufficient capacity or matching GPUs are unavailable.
        """

    @abstractmethod
    async def release_gpus(self, job_id: str) -> None:
        """Release any GPU device reservations held by the designated job.

        Args:
            job_id: Unique job identifier whose reserved GPUs should be freed.
        """

    @abstractmethod
    async def get_device_health(self) -> dict[int, bool]:
        """Query operational health diagnostics across all detected GPUs.

        Returns:
            Dictionary mapping device index to health status (True if healthy).
        """

    @abstractmethod
    async def get_active_allocations(self) -> dict[str, GpuAllocation]:
        """Retrieve all currently active job GPU allocations.

        Returns:
            Dictionary mapping job_id to active GpuAllocation.
        """


__all__ = [
    "GpuDeviceManagerPort",
]
