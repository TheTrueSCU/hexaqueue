"""Scanner daemon and task queue port interfaces.

Notes/Architectural Intent:
    Defines abstract contracts for security worker daemon loops, asynchronous
    task polling, and quarantine lifecycle event orchestration.
"""

from abc import ABC, abstractmethod

from hexaqueue_scanner.domain.models import CompositeScanReport, ScannerMetrics


class ScanTaskQueuePort(ABC):
    """Abstract port interface for scan task delivery and queueing."""

    @abstractmethod
    async def enqueue_task(self, collateral_id: str) -> None:
        """Enqueue a collateral bundle identifier for security scanning.

        Args:
            collateral_id: Collateral bundle identifier awaiting scan.
        """

    @abstractmethod
    async def get_next_task(self, timeout_seconds: float = 1.0) -> str | None:
        """Retrieve the next pending collateral bundle identifier to scan.

        Args:
            timeout_seconds: Maximum time to wait for a task before returning None.

        Returns:
            The next collateral_id, or None if queue is empty or timed out.
        """

    @abstractmethod
    def queue_size(self) -> int:
        """Return the number of scan tasks currently waiting in the queue.

        Returns:
            Non-negative integer queue depth.
        """


class ScannerDaemonPort(ABC):
    """Abstract port interface for the dedicated security worker daemon."""

    @abstractmethod
    async def start(self) -> None:
        """Start the background scanner worker loop."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the background scanner worker loop."""

    @abstractmethod
    async def process_bundle(self, collateral_id: str) -> CompositeScanReport:
        """Process, scan, and orchestrate promotion or quarantine for a collateral bundle.

        Args:
            collateral_id: Identifier of the collateral bundle to scan.

        Returns:
            CompositeScanReport detailing the outcome of the security inspection.
        """

    @abstractmethod
    def get_metrics(self) -> ScannerMetrics:
        """Retrieve current real-time scanner operational metrics.

        Returns:
            ScannerMetrics snapshot.
        """

    @abstractmethod
    def is_running(self) -> bool:
        """Check whether the background scanner loop is currently running.

        Returns:
            True if daemon loop is active, False otherwise.
        """


__all__ = [
    "ScannerDaemonPort",
    "ScanTaskQueuePort",
]
