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
    _ = await task

    rec_len = len(received)
    assert rec_len == 1
    rec_id = received[0].worker_id
    assert rec_id == "target-worker"
    # Subscriber cleaned up from dictionary
    assert "target-worker" not in collector._subscribers


def test_read_memory_mb_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify memory parsing arithmetic and zero boundary fallback."""
    from pathlib import Path

    collector = LocalTelemetryCollector()

    # 1. Normal /proc/meminfo parsing
    meminfo_content = "MemTotal:        16384000 kB\nMemAvailable:     8192000 kB\n"
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(Path, "read_text", lambda self: meminfo_content)

    used, total = collector._read_memory_mb()
    assert total == 16000
    assert used == 8000

    # 2. MemTotal is 0 -> falls back to default (2048, 8192)
    meminfo_zero = "MemTotal:               0 kB\nMemAvailable:           0 kB\n"
    monkeypatch.setattr(Path, "read_text", lambda self: meminfo_zero)
    used_fb, total_fb = collector._read_memory_mb()
    assert used_fb == 2048
    assert total_fb == 8192

    # 3. MemTotal is 1024 kB (mem_total == 1) -> boundary condition > 0 vs > 1
    meminfo_one = "MemTotal:            1024 kB\nMemAvailable:        1024 kB\n"
    monkeypatch.setattr(Path, "read_text", lambda self: meminfo_one)
    used_1, total_1 = collector._read_memory_mb()
    assert total_1 == 1
    assert used_1 == 0


def test_read_scratch_mb_statvfs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify scratch space calculation from statvfs blocks."""
    import os
    from collections import namedtuple

    StatVFS = namedtuple("StatVFS", ["f_blocks", "f_bfree", "f_frsize"])

    collector = LocalTelemetryCollector()

    # 200 blocks of 1MB = 200MB, 50 free = 50MB free, 150MB used
    mock_stat = StatVFS(f_blocks=200, f_bfree=50, f_frsize=1024 * 1024)
    monkeypatch.setattr(os, "statvfs", lambda p: mock_stat)

    used, total = collector._read_scratch_mb("/tmp")
    assert total == 200
    assert used == 150


def test_collect_pulse_cpu_calculation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify CPU percentage computation from loadavg and cpu_count."""
    import os

    collector = LocalTelemetryCollector()

    # 1. 2.5 loadavg with 4 cpus -> 62.5%
    monkeypatch.setattr(os, "getloadavg", lambda: (2.5, 1.0, 0.5))
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    pulse = collector.collect_pulse(worker_id="w-cpu")
    assert pulse.cpu_utilization_pct == 62.5

    # 2. cpu_count is None -> falls back to 1
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    monkeypatch.setattr(os, "getloadavg", lambda: (0.45, 0.2, 0.1))
    pulse_none = collector.collect_pulse(worker_id="w-cpu2")
    assert pulse_none.cpu_utilization_pct == 45.0
