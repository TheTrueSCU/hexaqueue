"""Unit tests for GPU device manager adapters and dynamic device allocation."""

import pytest

from hexaqueue_core.domain.exceptions import GpuAllocationError
from hexaqueue_core.domain.gpu import GpuDevice
from hexaqueue_worker.adapters.gpu import (
    MockGpuDeviceManagerAdapter,
    NvmlGpuDeviceManagerAdapter,
)


@pytest.fixture
def sample_gpus() -> list[GpuDevice]:
    """Provide a fixture of 4 diverse GPU devices for allocation testing."""
    return [
        GpuDevice(
            index=0,
            name="NVIDIA A100-SXM4-80GB",
            uuid="GPU-0",
            total_vram_mb=81920,
            free_vram_mb=81920,
            is_healthy=True,
        ),
        GpuDevice(
            index=1,
            name="NVIDIA A100-SXM4-80GB",
            uuid="GPU-1",
            total_vram_mb=81920,
            free_vram_mb=81920,
            is_healthy=True,
        ),
        GpuDevice(
            index=2,
            name="NVIDIA H100-SXM5-80GB",
            uuid="GPU-2",
            total_vram_mb=81920,
            free_vram_mb=81920,
            is_healthy=True,
        ),
        GpuDevice(
            index=3,
            name="NVIDIA T4",
            uuid="GPU-3",
            total_vram_mb=16384,
            free_vram_mb=16384,
            is_healthy=False,  # Unhealthy device
        ),
    ]


@pytest.mark.asyncio
async def test_gpu_device_enumeration(sample_gpus: list[GpuDevice]) -> None:
    """Verify listing all configured devices."""
    mgr = MockGpuDeviceManagerAdapter(devices=sample_gpus)
    devices = await mgr.enumerate_devices()
    count = len(devices)
    assert count == 4


@pytest.mark.asyncio
async def test_gpu_allocation_mutual_exclusion(sample_gpus: list[GpuDevice]) -> None:
    """Verify consecutive job allocations receive non-overlapping device sets."""
    mgr = MockGpuDeviceManagerAdapter(devices=sample_gpus)

    # Allocate 2 GPUs to Job A
    alloc_a = await mgr.allocate_gpus("job-A", count=2)
    indices_a = alloc_a.device_indices
    env_a = alloc_a.cuda_visible_devices_env

    assert indices_a == [0, 1]
    assert env_a == "0,1"

    # Allocate 1 GPU to Job B (Device 2 is next available healthy)
    alloc_b = await mgr.allocate_gpus("job-B", count=1)
    indices_b = alloc_b.device_indices
    env_b = alloc_b.cuda_visible_devices_env

    assert indices_b == [2]
    assert env_b == "2"

    # Attempt to allocate another GPU: only device 3 is left, but it's unhealthy
    with pytest.raises(GpuAllocationError, match="Insufficient GPU capacity"):
        await mgr.allocate_gpus("job-C", count=1)

    # Release Job A and re-allocate
    await mgr.release_gpus("job-A")
    alloc_c = await mgr.allocate_gpus("job-C", count=1)
    indices_c = alloc_c.device_indices
    assert indices_c == [0]


@pytest.mark.asyncio
async def test_gpu_allocation_by_model_and_vram(sample_gpus: list[GpuDevice]) -> None:
    """Verify model architecture matching and minimum VRAM constraints."""
    mgr = MockGpuDeviceManagerAdapter(devices=sample_gpus)

    # Request H100 specifically
    alloc_h100 = await mgr.allocate_gpus("job-h100", count=1, model="h100")
    indices = alloc_h100.device_indices
    assert indices == [2]

    # Request with high VRAM requirement exceeding available devices
    with pytest.raises(GpuAllocationError, match="Insufficient GPU capacity"):
        await mgr.allocate_gpus("job-oversized", count=1, min_vram_mb=100_000)


@pytest.mark.asyncio
async def test_gpu_allocation_zero_count(sample_gpus: list[GpuDevice]) -> None:
    """Verify zero GPU allocation request returns empty allocation without error."""
    mgr = MockGpuDeviceManagerAdapter(devices=sample_gpus)
    alloc = await mgr.allocate_gpus("job-cpu", count=0)
    indices = alloc.device_indices
    env = alloc.cuda_visible_devices_env

    assert indices == []
    assert env == ""


@pytest.mark.asyncio
async def test_gpu_duplicate_allocation_error(sample_gpus: list[GpuDevice]) -> None:
    """Verify error when attempting to allocate to the same job_id twice."""
    mgr = MockGpuDeviceManagerAdapter(devices=sample_gpus)
    await mgr.allocate_gpus("job-1", count=1)

    with pytest.raises(
        GpuAllocationError, match="already has an active GPU allocation"
    ):
        await mgr.allocate_gpus("job-1", count=1)


@pytest.mark.asyncio
async def test_gpu_device_health_and_active_allocations(
    sample_gpus: list[GpuDevice],
) -> None:
    """Verify health reporting and active allocation mapping."""
    mgr = MockGpuDeviceManagerAdapter(devices=sample_gpus)
    health = await mgr.get_device_health()

    h0 = health.get(0)
    h3 = health.get(3)
    assert h0 is True
    assert h3 is False

    await mgr.allocate_gpus("job-1", count=1)
    active = await mgr.get_active_allocations()
    count = len(active)
    assert count == 1
    has_job = "job-1" in active
    assert has_job is True


def test_nvml_adapter_initialization() -> None:
    """Verify NvmlGpuDeviceManagerAdapter initializes safely on any platform."""
    # When initialized without arguments on a non-GPU host, it defaults gracefully to empty list
    adapter = NvmlGpuDeviceManagerAdapter()
    dev_dict = adapter._devices
    is_dict = isinstance(dev_dict, dict)
    assert is_dict is True


def test_nvml_adapter_discover_devices_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify parsing of nvidia-smi query output."""
    import shutil
    import subprocess

    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/nvidia-smi")

    csv_output = "0, NVIDIA RTX 4090, GPU-test-uuid, 24576, 20480\n"
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: csv_output)

    devices = NvmlGpuDeviceManagerAdapter._discover_devices()
    count = len(devices)
    assert count == 1
    d = devices[0]
    idx = d.index
    name = d.name
    total = d.total_vram_mb
    free = d.free_vram_mb
    assert idx == 0
    assert name == "NVIDIA RTX 4090"
    assert total == 24576
    assert free == 20480


def test_nvml_adapter_discover_devices_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify graceful handling when nvidia-smi command raises error."""
    import shutil
    import subprocess

    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/nvidia-smi")

    def mock_fail(*args, **kwargs):
        raise subprocess.SubprocessError("device error")

    monkeypatch.setattr(subprocess, "check_output", mock_fail)

    devices = NvmlGpuDeviceManagerAdapter._discover_devices()
    count = len(devices)
    assert count == 0
