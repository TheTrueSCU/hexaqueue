"""Unit tests for GPU domain models and validation invariants."""

import pytest
from pydantic import ValidationError

from hexaqueue_core.domain.gpu import GpuAllocation, GpuDevice


def test_gpu_device_creation_and_attributes() -> None:
    """Verify standard GpuDevice creation and field mappings."""
    device = GpuDevice(
        index=0,
        name="NVIDIA A100-SXM4-80GB",
        uuid="GPU-fa20-410a",
        total_vram_mb=81920,
        free_vram_mb=81920,
        is_healthy=True,
        temperature_c=42,
    )
    idx = device.index
    name = device.name
    total = device.total_vram_mb
    free = device.free_vram_mb
    healthy = device.is_healthy
    temp = device.temperature_c

    assert idx == 0
    assert name == "NVIDIA A100-SXM4-80GB"
    assert total == 81920
    assert free == 81920
    assert healthy is True
    assert temp == 42


def test_gpu_device_validation_errors() -> None:
    """Verify validation on empty strings and exceeding memory bounds."""
    with pytest.raises(ValidationError):
        GpuDevice(
            index=0,
            name="",
            uuid="GPU-1",
            total_vram_mb=1000,
            free_vram_mb=500,
        )

    with pytest.raises(ValidationError):
        GpuDevice(
            index=0,
            name="A100",
            uuid="",
            total_vram_mb=1000,
            free_vram_mb=500,
        )

    # Free memory greater than total
    with pytest.raises(ValidationError):
        GpuDevice(
            index=0,
            name="A100",
            uuid="GPU-1",
            total_vram_mb=1000,
            free_vram_mb=1500,
        )


def test_gpu_allocation_cuda_visible_devices() -> None:
    """Verify CUDA_VISIBLE_DEVICES string formatting from allocated indices."""
    alloc = GpuAllocation(job_id="job-101", device_indices=[3, 1, 2])
    env_str = alloc.cuda_visible_devices_env
    job_id = alloc.job_id
    indices = alloc.device_indices

    assert job_id == "job-101"
    assert indices == [3, 1, 2]
    assert env_str == "1,2,3"


def test_gpu_allocation_empty_indices() -> None:
    """Verify empty device indices formatting."""
    alloc = GpuAllocation(job_id="job-cpu-only", device_indices=[])
    env_str = alloc.cuda_visible_devices_env
    assert env_str == ""


def test_gpu_allocation_validation_errors() -> None:
    """Verify validation on duplicate device indices or empty job_id."""
    with pytest.raises(ValidationError):
        GpuAllocation(job_id="", device_indices=[0])

    with pytest.raises(ValidationError):
        GpuAllocation(job_id="job-1", device_indices=[1, 1])

    with pytest.raises(ValidationError):
        GpuAllocation(job_id="job-1", device_indices=[-1])
