"""Background monitor and budget reconciliation daemon.

Notes/Architectural Intent:
    Periodically executes cluster health sweeps, flags uncommunicative/dead worker nodes,
    and reclaims expired budget reservation holds to prevent credit leakage.
    Provides a deterministic `run_once()` method for hermetic testing.
"""

import asyncio
import contextlib

from hexaqueue_monitor.adapters.ledger import InMemoryBudgetLedgerAdapter
from hexaqueue_monitor.domain.config import MonitorConfig
from hexaqueue_monitor.ports.monitor import ClusterMonitorPort


class MonitorDaemon:
    """Background monitoring daemon orchestrating periodic health checks and budget garbage collection.

    Args:
        cluster_monitor: ClusterMonitorPort implementation.
        budget_ledger: InMemoryBudgetLedgerAdapter implementation.
        config: Optional MonitorConfig settings.
    """

    def __init__(
        self,
        cluster_monitor: ClusterMonitorPort,
        budget_ledger: InMemoryBudgetLedgerAdapter,
        config: MonitorConfig | None = None,
    ) -> None:
        self._monitor = cluster_monitor
        self._ledger = budget_ledger
        self._config = config or MonitorConfig()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._sweep_count = 0

    @property
    def is_running(self) -> bool:
        """Return True if background loop is actively running."""
        return self._running

    @property
    def sweep_count(self) -> int:
        """Return count of completed reconciliation sweeps."""
        return self._sweep_count

    async def run_once(self) -> tuple[list[str], list[str]]:
        """Execute a single synchronous sweep of dead node detection and stale reservation expiration.

        Returns:
            Tuple of (dead_worker_ids, expired_reservation_ids).
        """
        dead_workers = await self._monitor.reap_dead_nodes(
            dead_threshold_seconds=self._config.dead_threshold_seconds
        )
        expired_holds = await self._ledger.expire_stale_reservations(
            max_age_seconds=self._config.reservation_expiry_seconds
        )
        self._sweep_count += 1
        return dead_workers, expired_holds

    async def start(self) -> None:
        """Start the background monitoring loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Gracefully stop the background monitoring loop."""
        if not self._running:
            return
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        """Internal periodic execution loop."""
        while self._running:
            with contextlib.suppress(Exception):
                await self.run_once()
            try:
                await asyncio.sleep(self._config.reaper_interval_seconds)
            except asyncio.CancelledError:
                break


__all__ = [
    "MonitorDaemon",
]
