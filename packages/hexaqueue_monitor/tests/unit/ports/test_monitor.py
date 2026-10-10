"""Unit tests for ClusterMonitorPort abstract contract."""

import pytest

from hexaqueue_monitor.domain.models import (
    ClusterHealthReport,
    NodeTelemetryPulse,
)
from hexaqueue_monitor.ports.monitor import ClusterMonitorPort


class DummyClusterMonitor(ClusterMonitorPort):
    """Hermetic test implementation of ClusterMonitorPort."""

    async def record_pulse(self, pulse: NodeTelemetryPulse) -> None:
        pass

    async def get_cluster_health(self) -> ClusterHealthReport:
        return ClusterHealthReport(
            healthy_nodes_count=1,
            unhealthy_nodes_count=0,
            dead_nodes_count=0,
            total_cpus=8,
            allocated_cpus=2,
            total_ram_mb=8192,
            allocated_ram_mb=2048,
            total_gpus=0,
            allocated_gpus=0,
            active_jobs_count=1,
        )

    async def get_node_pulse(self, worker_id: str) -> NodeTelemetryPulse | None:
        return None

    async def list_node_pulses(self) -> list[NodeTelemetryPulse]:
        return []

    async def reap_dead_nodes(
        self, dead_threshold_seconds: float | None = None
    ) -> list[str]:
        return []


@pytest.mark.asyncio
async def test_cluster_monitor_contract() -> None:
    """Verify dummy implementation fulfills ClusterMonitorPort."""
    monitor = DummyClusterMonitor()
    health = await monitor.get_cluster_health()
    assert health.healthy_nodes_count == 1
    assert health.allocated_cpus == 2


__all__ = [
    "DummyClusterMonitor",
    "test_cluster_monitor_contract",
]
