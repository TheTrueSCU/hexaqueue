"""GPU hardware discovery and dynamic device isolation adapters.

Notes/Architectural Intent:
    Provides compute node GPU management backed by NVML device queries or simulated
    hardware topology. Coordinates dynamic allocation of discrete physical GPU indices
    to executing jobs, guaranteeing mutual exclusion and generating formatted
    CUDA_VISIBLE_DEVICES environment strings.
"""

import asyncio
import shutil
import subprocess
from datetime import UTC, datetime

from hexaqueue_core.domain.exceptions import GpuAllocationError
from hexaqueue_core.domain.gpu import GpuAllocation, GpuDevice
from hexaqueue_core.ports.gpu import GpuDeviceManagerPort


class MockGpuDeviceManagerAdapter(GpuDeviceManagerPort):
    """In-memory simulated GPU device manager adapter for testing and evaluation.

    Args:
        devices: Initial list of GpuDevice models representing available node hardware.
    """

    def __init__(self, devices: list[GpuDevice] | None = None) -> None:
        self._devices: dict[int, GpuDevice] = {d.index: d for d in (devices or [])}
        self._allocations: dict[str, GpuAllocation] = {}
        self._lock = asyncio.Lock()

    async def enumerate_devices(self) -> list[GpuDevice]:
        """Enumerate all configured GPU accelerator devices."""
        async with self._lock:
            return list(self._devices.values())

    async def allocate_gpus(
        self,
        job_id: str,
        count: int,
        model: str | None = None,
        min_vram_mb: int | None = None,
    ) -> GpuAllocation:
        """Allocate discrete GPU devices to a job under mutual exclusion.

        Args:
            job_id: Unique job identifier requesting allocation.
            count: Number of GPUs required.
            model: Optional case-insensitive architecture substring filter.
            min_vram_mb: Optional minimum VRAM per GPU in megabytes.

        Returns:
            GpuAllocation containing assigned device indices.

        Raises:
            GpuAllocationError: If capacity is insufficient or job already holds an allocation.
        """
        if count <= 0:
            return GpuAllocation(job_id=job_id, device_indices=[])

        async with self._lock:
            if job_id in self._allocations:
                msg = f"Job '{job_id}' already has an active GPU allocation"
                raise GpuAllocationError(msg)

            # Find all currently reserved device indices
            reserved_indices: set[int] = set()
            for alloc in self._allocations.values():
                reserved_indices.update(alloc.device_indices)

            # Filter candidate devices
            candidates: list[GpuDevice] = []
            for dev in self._devices.values():
                if dev.index in reserved_indices:
                    continue
                if not dev.is_healthy:
                    continue
                if model and model.lower() not in dev.name.lower():
                    continue
                if min_vram_mb and dev.total_vram_mb < min_vram_mb:
                    continue
                candidates.append(dev)

            if len(candidates) < count:
                msg = (
                    f"Insufficient GPU capacity for job '{job_id}': "
                    f"requested {count}, available matching {len(candidates)}"
                )
                raise GpuAllocationError(msg)

            chosen = candidates[:count]
            chosen_indices = [d.index for d in chosen]
            allocation = GpuAllocation(
                job_id=job_id,
                device_indices=chosen_indices,
                allocated_at=datetime.now(UTC),
            )
            self._allocations[job_id] = allocation
            return allocation

    async def release_gpus(self, job_id: str) -> None:
        """Release assigned GPUs held by the specified job."""
        async with self._lock:
            self._allocations.pop(job_id, None)

    async def get_device_health(self) -> dict[int, bool]:
        """Query health diagnostics across all managed devices."""
        async with self._lock:
            return {idx: d.is_healthy for idx, d in self._devices.items()}

    async def get_active_allocations(self) -> dict[str, GpuAllocation]:
        """Retrieve all currently active allocations."""
        async with self._lock:
            return dict(self._allocations)


class NvmlGpuDeviceManagerAdapter(MockGpuDeviceManagerAdapter):
    """GPU device manager adapter backed by NVML or nvidia-smi CLI discovery.

    Args:
        devices: Optional pre-configured devices. If None, host driver discovery is attempted.
    """

    def __init__(self, devices: list[GpuDevice] | None = None) -> None:
        initial_devices = devices if devices is not None else self._discover_devices()
        super().__init__(devices=initial_devices)

    @classmethod
    def _discover_devices(cls) -> list[GpuDevice]:
        """Query host GPU topology via nvidia-smi command-line utility.

        Returns:
            List of discovered GpuDevice models, or empty list if no NVIDIA driver exists.
        """
        if not shutil.which("nvidia-smi"):
            return []

        cmd = [
            "nvidia-smi",
            "--query-gpu=index,name,uuid,memory.total,memory.free",
            "--format=csv,noheader,nounits",
        ]
        try:
            output = subprocess.check_output(  # noqa: S603
                cmd,
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            devices: list[GpuDevice] = []
            for line in output.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 5:
                    idx = int(parts[0])
                    name = parts[1]
                    uuid = parts[2]
                    total_mb = int(parts[3])
                    free_mb = int(parts[4])
                    devices.append(
                        GpuDevice(
                            index=idx,
                            name=name,
                            uuid=uuid,
                            total_vram_mb=max(1, total_mb),
                            free_vram_mb=max(0, free_mb),
                            is_healthy=True,
                        )
                    )
            return devices
        except (subprocess.SubprocessError, OSError, ValueError):
            return []


__all__ = [
    "MockGpuDeviceManagerAdapter",
    "NvmlGpuDeviceManagerAdapter",
]
