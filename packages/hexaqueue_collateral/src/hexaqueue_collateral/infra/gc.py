"""Periodic garbage collection runner for unpinned temporary collateral.

Notes/Architectural Intent:
    Provides an asynchronous background loop for continuously purging expired
    temporary collateral bundles based on TTL and high-watermark storage budget.
    Ensures that permanent artifacts and actively pinned execution collateral
    are strictly protected from eviction.
"""

import asyncio
import contextlib
import logging
from typing import Self

from hexaqueue_collateral.ports.service import CollateralServicePort

logger = logging.getLogger(__name__)


class CollateralGcRunner:
    """Recurring garbage collection daemon for Content-Addressable Storage (CAS).

    Args:
        service: CollateralServicePort instance to execute evictions against.
        interval_seconds: Frequency in seconds between eviction cycles.
        max_age_seconds: Optional default TTL in seconds for temporary collateral.
        high_watermark_bytes: Optional storage threshold triggering LRU eviction.

    Notes/Architectural Intent:
        Runs in the background without blocking the scheduler or HTTP API.
        Fails safely on unexpected exceptions by logging warnings without terminating
        the recurring loop.
    """

    def __init__(
        self,
        service: CollateralServicePort,
        interval_seconds: float = 300.0,
        max_age_seconds: int | None = None,
        high_watermark_bytes: int | None = None,
    ) -> None:
        self._service = service
        self._interval_seconds = interval_seconds
        self._max_age_seconds = max_age_seconds
        self._high_watermark_bytes = high_watermark_bytes
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        """Return whether the GC daemon is actively running."""
        return self._running

    async def start(self) -> Self:
        """Start the background eviction loop.

        Returns:
            The started CollateralGcRunner instance.
        """
        async with self._lock:
            if self._running:
                return self
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info(
                "Started CollateralGcRunner (interval=%.1fs, max_age=%s, watermark=%s)",
                self._interval_seconds,
                self._max_age_seconds,
                self._high_watermark_bytes,
            )
            return self

    async def stop(self) -> None:
        """Stop the background eviction loop gracefully."""
        async with self._lock:
            if not self._running:
                return
            self._running = False
            if self._task and not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
            self._task = None
            logger.info("Stopped CollateralGcRunner")

    async def run_once(self) -> list[str]:
        """Execute a single sweep of garbage collection.

        Returns:
            List of evicted collateral bundle IDs.

        Notes/Architectural Intent:
            Can be invoked directly by tests or administrative maintenance triggers
            without running the background timer loop.
        """
        try:
            evicted = await self._service.evict_expired(
                max_age_seconds=self._max_age_seconds,
                high_watermark_bytes=self._high_watermark_bytes,
            )
            if evicted:
                logger.info(
                    "Collateral GC sweep evicted %d bundles: %s", len(evicted), evicted
                )
            return evicted
        except Exception:
            logger.exception("Error during Collateral GC sweep")
            return []

    async def _run_loop(self) -> None:
        """Internal background polling loop."""
        while self._running:
            try:
                await asyncio.sleep(self._interval_seconds)
                if not self._running:
                    break
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Unexpected error in CollateralGcRunner loop")


__all__ = [
    "CollateralGcRunner",
]
