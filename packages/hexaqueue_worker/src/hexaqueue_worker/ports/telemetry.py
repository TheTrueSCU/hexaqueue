"""Port interface for worker telemetry pulse emission and subscription.

Notes/Architectural Intent:
    Defines the contract for hardware metric collection and distribution across
    `hexaqueue-worker`, `hexaqueue-server`, and `hexaqueue-monitor`.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


class TelemetryEmitterPort(ABC):
    """Abstract port for collecting and broadcasting worker node telemetry."""

    @abstractmethod
    async def emit_pulse(self, pulse: NodeTelemetryPulse) -> None:
        """Publish a telemetry pulse.

        Args:
            pulse: NodeTelemetryPulse payload.
        """

    @abstractmethod
    def subscribe_pulses(
        self, worker_id: str | None = None
    ) -> AsyncIterator[NodeTelemetryPulse]:
        """Subscribe to telemetry pulses from a specific or all workers.

        Args:
            worker_id: Optional worker identifier filter.

        Yields:
            NodeTelemetryPulse instances in chronological sequence.
        """


__all__ = [
    "TelemetryEmitterPort",
]
