"""Unit tests for LocalTelemetryCollector adapter."""

import asyncio

import pytest

from hexaqueue_worker.adapters.telemetry import LocalTelemetryCollector
from hexaqueue_worker.domain.telemetry import GpuTelemetry, NodeTelemetryPulse


def test_collect_pulse_local_system() -> None:
    """Verify local telemetry pulse collection."""

    def _mock_gpus() -> list[GpuTelemetry]:
        return [
            GpuTelemetry(
                index=0,
                model="NVIDIA RTX 4090",
                utilization_pct=50.0,
                vram_used_mb=12288,
                vram_total_mb=24576,
            )
        ]

    collector = LocalTelemetryCollector(gpu_telemetry_provider=_mock_gpus)
    pulse = collector.collect_pulse(worker_id="test-worker", active_jobs=2)

    w_id = pulse.worker_id
    assert w_id == "test-worker"
    active = pulse.active_jobs
    assert active == 2
    mem_total = pulse.memory_total_mb
    assert mem_total > 0
    scratch_total = pulse.scratch_total_mb
    assert scratch_total > 0
    gpus_len = len(pulse.gpu_metrics)
    assert gpus_len == 1
    gpu_model = pulse.gpu_metrics[0].model
    assert "RTX 4090" in gpu_model


@pytest.mark.asyncio
async def test_emit_and_subscribe_pulses() -> None:
    """Verify pub/sub pulse distribution and filtering."""
    collector = LocalTelemetryCollector()
    received: list[NodeTelemetryPulse] = []

    async def _listener() -> None:
        async for p in collector.subscribe_pulses("target-worker"):
            received.append(p)

    task = asyncio.create_task(_listener())
    await asyncio.sleep(0.01)

    pulse_target = NodeTelemetryPulse(
        worker_id="target-worker",
        memory_used_mb=1024,
        memory_total_mb=4096,
        scratch_used_mb=512,
        scratch_total_mb=2048,
    )
    pulse_other = NodeTelemetryPulse(
        worker_id="other-worker",
        memory_used_mb=2048,
        memory_total_mb=8192,
        scratch_used_mb=1024,
        scratch_total_mb=4096,
    )

    await collector.emit_pulse(pulse_target)
    await collector.emit_pulse(pulse_other)
    await asyncio.sleep(0.01)

    await collector.close()
    await task

    rec_len = len(received)
    assert rec_len == 1
    rec_id = received[0].worker_id
    assert rec_id == "target-worker"
