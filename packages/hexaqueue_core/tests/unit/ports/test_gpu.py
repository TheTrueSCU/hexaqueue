"""Unit tests for GpuDeviceManagerPort interface contract."""

import pytest

from hexaqueue_core.domain.gpu import GpuAllocation, GpuDevice
from hexaqueue_core.ports.gpu import GpuDeviceManagerPort


class DummyGpuDeviceManager(GpuDeviceManagerPort):
    """Concrete test implementation of GpuDeviceManagerPort."""

    def __init__(self, devices: list[GpuDevice]) -> None:
        self._devices = devices
        self._allocations: dict[str, GpuAllocation] = {}

    async def enumerate_devices(self) -> list[GpuDevice]:
        return list(self._devices)

    async def allocate_gpus(
        self,
        job_id: str,
        count: int,
        model: str | None = None,
        min_vram_mb: int | None = None,
    ) -> GpuAllocation:
        alloc = GpuAllocation(job_id=job_id, device_indices=[0])
        self._allocations[job_id] = alloc
        return alloc

    async def release_gpus(self, job_id: str) -> None:
        self._allocations.pop(job_id, None)

    async def get_device_health(self) -> dict[int, bool]:
        return {d.index: d.is_healthy for d in self._devices}

    async def get_active_allocations(self) -> dict[str, GpuAllocation]:
        return dict(self._allocations)


@pytest.mark.asyncio
async def test_gpu_device_manager_port_contract() -> None:
    """Verify standard methods of GpuDeviceManagerPort contract."""
    device = GpuDevice(
        index=0,
        name="NVIDIA H100",
        uuid="GPU-001",
        total_vram_mb=81920,
        free_vram_mb=81920,
    )
    mgr = DummyGpuDeviceManager([device])

    devices = await mgr.enumerate_devices()
    dev_count = len(devices)
    assert dev_count == 1

    health = await mgr.get_device_health()
    is_healthy = health.get(0)
    assert is_healthy is True

    alloc = await mgr.allocate_gpus("job-1", count=1)
    env = alloc.cuda_visible_devices_env
    assert env == "0"

    active = await mgr.get_active_allocations()
    active_count = len(active)
    assert active_count == 1

    await mgr.release_gpus("job-1")
    active_after = await mgr.get_active_allocations()
    after_count = len(active_after)
    assert after_count == 0
