"""Unit tests for LocalClusterMonitorAdapter."""

from datetime import UTC, datetime

import pytest

from hexaqueue_monitor.adapters.local import LocalClusterMonitorAdapter
from hexaqueue_monitor.domain.config import MonitorConfig
from hexaqueue_monitor.domain.models import GpuTelemetry, NodeTelemetryPulse


@pytest.mark.asyncio
async def test_cluster_monitor_pulse_recording() -> None:
    """Verify recording node telemetry pulse updates monitor cache and health report."""
    cfg = MonitorConfig(unhealthy_threshold_seconds=10.0, dead_threshold_seconds=20.0)
    monitor = LocalClusterMonitorAdapter(config=cfg)

    gpu = GpuTelemetry(
        index=0,
        model="A100",
        power_w=200.0,
        temperature_c=50.0,
        utilization_pct=90.0,
        vram_total_mb=40960,
        vram_used_mb=20480,
    )
    pulse = NodeTelemetryPulse(
        worker_id="worker-node-1",
        timestamp=datetime.now(UTC),
        cpu_utilization_pct=45.0,
        load_average=(1.2, 0.9, 0.6),
        memory_used_mb=16384,
        memory_total_mb=65536,
        scratch_used_mb=5000,
        scratch_total_mb=50000,
        active_jobs=3,
        gpu_metrics=[gpu],
    )

    await monitor.record_pulse(pulse)

    cached_pulse = await monitor.get_node_pulse("worker-node-1")
    assert cached_pulse is not None
    assert cached_pulse.worker_id == "worker-node-1"

    all_pulses = await monitor.list_node_pulses()
    assert len(all_pulses) == 1

    health = await monitor.get_cluster_health()
    assert health.healthy_nodes_count == 1
    assert health.unhealthy_nodes_count == 0
    assert health.dead_nodes_count == 0
    assert health.active_jobs_count == 3
    assert health.total_gpus == 1
    assert health.allocated_gpus == 1


@pytest.mark.asyncio
async def test_cluster_monitor_reap_dead_nodes() -> None:
    """Verify reaper sweep marks nodes as DEAD when pulse threshold is exceeded."""
    monitor = LocalClusterMonitorAdapter(
        config=MonitorConfig(dead_threshold_seconds=0.0)
    )
    pulse = NodeTelemetryPulse(
        worker_id="worker-dead-1",
        memory_used_mb=1024,
        memory_total_mb=4096,
        scratch_used_mb=100,
        scratch_total_mb=1000,
    )
    await monitor.record_pulse(pulse)

    dead_nodes = await monitor.reap_dead_nodes(dead_threshold_seconds=-1.0)
    assert "worker-dead-1" in dead_nodes

    health = await monitor.get_cluster_health()
    assert health.dead_nodes_count == 1
    assert health.healthy_nodes_count == 0


__all__ = [
    "test_cluster_monitor_pulse_recording",
    "test_cluster_monitor_reap_dead_nodes",
]
