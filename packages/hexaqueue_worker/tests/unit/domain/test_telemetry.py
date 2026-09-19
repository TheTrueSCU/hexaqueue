"""Unit tests for telemetry domain models."""

import pytest

from hexaqueue_worker.domain.telemetry import GpuTelemetry, NodeTelemetryPulse


def test_gpu_telemetry_instantiation() -> None:
    """Verify GpuTelemetry creation and attributes."""
    gpu = GpuTelemetry(
        index=0,
        model="NVIDIA A100-SXM4-80GB",
        utilization_pct=85.5,
        vram_used_mb=40960,
        vram_total_mb=81920,
        temperature_c=62.0,
        power_w=300.0,
    )
    idx = gpu.index
    assert idx == 0
    util = gpu.utilization_pct
    assert util == 85.5
    model_name = gpu.model
    assert "A100" in model_name


def test_node_telemetry_pulse_utilization_properties() -> None:
    """Verify memory and scratch utilization percentage calculations."""
    pulse = NodeTelemetryPulse(
        worker_id="worker-01",
        cpu_utilization_pct=42.0,
        load_average=(1.5, 1.2, 0.8),
        memory_used_mb=4096,
        memory_total_mb=16384,
        scratch_used_mb=5120,
        scratch_total_mb=20480,
        active_jobs=3,
    )
    mem_pct = pulse.memory_utilization_pct
    assert mem_pct == 25.0
    scratch_pct = pulse.scratch_utilization_pct
    assert scratch_pct == 25.0
    active = pulse.active_jobs
    assert active == 3


def test_node_telemetry_pulse_empty_worker_id() -> None:
    """Verify empty worker_id raises ValueError."""
    with pytest.raises(ValueError, match="worker_id cannot be empty"):
        NodeTelemetryPulse(
            worker_id="  ",
            memory_used_mb=1024,
            memory_total_mb=8192,
            scratch_used_mb=512,
            scratch_total_mb=4096,
        )
