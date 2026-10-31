"""In-memory task queue adapter for scanner daemon.

Notes/Architectural Intent:
    Provides an asyncio.Queue-backed implementation of ScanTaskQueuePort for
    local development, embedded controllers, and standalone test harnesses.
"""

import asyncio

from hexaqueue_scanner.ports.daemon import ScanTaskQueuePort


class InMemoryScanTaskQueueAdapter(ScanTaskQueuePort):
    """In-memory asynchronous task queue for scanner bundles."""

    def __init__(self, maxsize: int = 0) -> None:
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)

    async def enqueue_task(self, collateral_id: str) -> None:
        """Enqueue a collateral bundle identifier for security scanning.

        Args:
            collateral_id: Collateral bundle identifier awaiting scan.
        """
        await self._queue.put(collateral_id)

    async def get_next_task(self, timeout_seconds: float = 1.0) -> str | None:
        """Retrieve the next pending collateral bundle identifier to scan.

        Args:
            timeout_seconds: Maximum time to wait for a task before returning None.

        Returns:
            The next collateral_id, or None if queue is empty or timed out.
        """
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout_seconds)
        except TimeoutError:
            return None

    def queue_size(self) -> int:
        """Return the number of scan tasks currently waiting in the queue.

        Returns:
            Non-negative integer queue depth.
        """
        return self._queue.qsize()


__all__ = [
    "InMemoryScanTaskQueueAdapter",
]
