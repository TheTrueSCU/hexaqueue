"""Cluster monitor and node telemetry port interfaces.

Notes/Architectural Intent:
    Defines abstract contracts for recording worker telemetry pulses,
    aggregating point-in-time cluster capacity reports, and identifying dead or uncommunicative nodes.
"""

from abc import ABC, abstractmethod

from hexaqueue_monitor.domain.models import (
    ClusterHealthReport,
    NodeTelemetryPulse,
)


class ClusterMonitorPort(ABC):
    """Abstract port interface for worker telemetry aggregation and cluster health reporting."""

    @abstractmethod
    async def record_pulse(self, pulse: NodeTelemetryPulse) -> None:
        """Record an incoming telemetry pulse from a compute worker node.

        Args:
            pulse: Populated NodeTelemetryPulse.
        """

    @abstractmethod
    async def get_cluster_health(self) -> ClusterHealthReport:
        """Generate point-in-time cluster capacity and health report.

        Returns:
            ClusterHealthReport aggregating active, unhealthy, and dead nodes.
        """

    @abstractmethod
    async def get_node_pulse(self, worker_id: str) -> NodeTelemetryPulse | None:
        """Retrieve the latest telemetry pulse recorded for a specific worker.

        Args:
            worker_id: Target compute node identifier.

        Returns:
            Latest recorded NodeTelemetryPulse or None if not registered.
        """

    @abstractmethod
    async def list_node_pulses(self) -> list[NodeTelemetryPulse]:
        """List the latest telemetry pulses for all registered worker nodes.

        Returns:
            List of active NodeTelemetryPulse records.
        """

    @abstractmethod
    async def reap_dead_nodes(
        self, dead_threshold_seconds: float | None = None
    ) -> list[str]:
        """Detect and return identifiers of worker nodes whose pulse age exceeds the threshold.

        Args:
            dead_threshold_seconds: Optional threshold override in seconds.

        Returns:
            List of worker identifiers transitioned to DEAD state.
        """


__all__ = [
    "ClusterMonitorPort",
]
