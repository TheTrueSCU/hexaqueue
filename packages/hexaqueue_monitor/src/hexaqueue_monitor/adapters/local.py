"""Local in-memory cluster monitor and node telemetry adapter.

Notes/Architectural Intent:
    Ingests worker telemetry pulses, classifies worker node health states
    (HEALTHY, UNHEALTHY, DEAD) based on pulse freshness, and aggregates
    cluster-wide capacity metrics into real-time health reports.
"""

import asyncio
from datetime import UTC, datetime

from hexaqueue_monitor.domain.config import MonitorConfig
from hexaqueue_monitor.domain.models import (
    ClusterHealthReport,
    NodeTelemetryPulse,
)
from hexaqueue_monitor.ports.monitor import ClusterMonitorPort


class LocalClusterMonitorAdapter(ClusterMonitorPort):
    """Local in-memory cluster health and telemetry aggregation adapter.

    Args:
        config: Optional MonitorConfig thresholds.
    """

    def __init__(self, config: MonitorConfig | None = None) -> None:
        self._config = config or MonitorConfig()
        self._pulses: dict[str, NodeTelemetryPulse] = {}
        self._last_seen: dict[str, datetime] = {}
        self._dead_nodes: set[str] = set()
        self._lock = asyncio.Lock()

    async def record_pulse(self, pulse: NodeTelemetryPulse) -> None:
        """Record an incoming telemetry pulse from a compute worker node.

        Args:
            pulse: Populated NodeTelemetryPulse.
        """
        async with self._lock:
            self._pulses[pulse.worker_id] = pulse
            self._last_seen[pulse.worker_id] = datetime.now(UTC)
            self._dead_nodes.discard(pulse.worker_id)

    async def get_node_pulse(self, worker_id: str) -> NodeTelemetryPulse | None:
        """Retrieve the latest telemetry pulse recorded for a specific worker.

        Args:
            worker_id: Target compute node identifier.

        Returns:
            Latest recorded NodeTelemetryPulse or None if not registered.
        """
        async with self._lock:
            return self._pulses.get(worker_id)

    async def list_node_pulses(self) -> list[NodeTelemetryPulse]:
        """List the latest telemetry pulses for all registered worker nodes.

        Returns:
            List of active NodeTelemetryPulse records.
        """
        async with self._lock:
            return list(self._pulses.values())

    async def reap_dead_nodes(
        self, dead_threshold_seconds: float | None = None
    ) -> list[str]:
        """Detect worker nodes whose heartbeat pulse age exceeds the threshold.

        Args:
            dead_threshold_seconds: Optional threshold override in seconds.

        Returns:
            List of worker identifiers transitioned to DEAD state during this sweep.
        """
        threshold = (
            dead_threshold_seconds
            if dead_threshold_seconds is not None
            else self._config.dead_threshold_seconds
        )
        now = datetime.now(UTC)
        newly_dead: list[str] = []

        async with self._lock:
            for worker_id, last_time in self._last_seen.items():
                if worker_id not in self._dead_nodes:
                    age = (now - last_time).total_seconds()
                    if age > threshold:
                        self._dead_nodes.add(worker_id)
                        newly_dead.append(worker_id)
        return newly_dead

    async def get_cluster_health(self) -> ClusterHealthReport:
        """Generate point-in-time cluster capacity and health report.

        Returns:
            ClusterHealthReport aggregating healthy, unhealthy, and dead nodes.
        """
        now = datetime.now(UTC)
        async with self._lock:
            healthy_count = 0
            unhealthy_count = 0
            dead_count = len(self._dead_nodes)

            total_cpus = 0
            allocated_cpu_f = 0.0

            total_ram = 0
            allocated_ram = 0
            total_gpus = 0
            allocated_gpus = 0
            active_jobs = 0

            for worker_id, pulse in self._pulses.items():
                if worker_id in self._dead_nodes:
                    continue

                age = (now - self._last_seen[worker_id]).total_seconds()
                if age <= self._config.unhealthy_threshold_seconds:
                    healthy_count += 1
                elif age <= self._config.dead_threshold_seconds:
                    unhealthy_count += 1
                else:
                    dead_count += 1
                    continue

                total_cpus += 8  # Normalized default
                allocated_cpu_f += (pulse.cpu_utilization_pct / 100.0) * 8
                total_ram += pulse.memory_total_mb
                allocated_ram += pulse.memory_used_mb
                total_gpus += len(pulse.gpu_metrics)
                allocated_gpus += sum(
                    1 for g in pulse.gpu_metrics if g.utilization_pct > 0.0
                )
                active_jobs += pulse.active_jobs

            allocated_cpus = round(allocated_cpu_f)

            return ClusterHealthReport(
                active_jobs_count=active_jobs,
                allocated_cpus=max(0, allocated_cpus),
                allocated_gpus=allocated_gpus,
                allocated_ram_mb=allocated_ram,
                dead_nodes_count=dead_count,
                healthy_nodes_count=healthy_count,
                total_cpus=max(0, total_cpus),
                total_gpus=total_gpus,
                total_ram_mb=total_ram,
                unhealthy_nodes_count=unhealthy_count,
            )


__all__ = [
    "LocalClusterMonitorAdapter",
]
