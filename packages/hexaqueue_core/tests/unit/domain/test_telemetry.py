"""Unit tests for telemetry domain models in hexaqueue-core.

Notes/Architectural Intent:
    Tests GpuTelemetry and NodeTelemetryPulse instantiation, validation invariants,
    and computed utilization properties.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from hexaqueue_core.domain.telemetry import GpuTelemetry, NodeTelemetryPulse


def test_gpu_telemetry_instantiation() -> None:
    """Verify GpuTelemetry creation and bounds."""
    gpu = GpuTelemetry(
        index=0,
        model="NVIDIA H100",
        power_w=350.0,
        temperature_c=65.0,
        utilization_pct=85.0,
        vram_total_mb=81920,
        vram_used_mb=40960,
    )
    assert gpu.index == 0
    assert gpu.utilization_pct == 85.0
    assert gpu.vram_used_mb == 40960


def test_node_telemetry_pulse_utilization_properties() -> None:
    """Verify NodeTelemetryPulse calculates memory and scratch utilization correctly."""
    now = datetime.now(UTC)
    pulse = NodeTelemetryPulse(
        worker_id="worker-node-1",
        timestamp=now,
        cpu_utilization_pct=50.0,
        load_average=(1.0, 0.8, 0.5),
        memory_used_mb=8192,
        memory_total_mb=16384,
        scratch_used_mb=1000,
        scratch_total_mb=4000,
        active_jobs=2,
    )
    assert pulse.worker_id == "worker-node-1"
    assert pulse.memory_utilization_pct == 50.0
    assert pulse.scratch_utilization_pct == 25.0


def test_node_telemetry_pulse_empty_worker_id() -> None:
    """Verify empty worker_id fails validation."""
    with pytest.raises(ValidationError):
        NodeTelemetryPulse(
            worker_id="   ",
            memory_used_mb=1024,
            memory_total_mb=2048,
            scratch_used_mb=100,
            scratch_total_mb=200,
        )


__all__ = [
    "test_gpu_telemetry_instantiation",
    "test_node_telemetry_pulse_empty_worker_id",
    "test_node_telemetry_pulse_utilization_properties",
]
