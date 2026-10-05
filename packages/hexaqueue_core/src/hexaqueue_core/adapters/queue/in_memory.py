"""In-memory priority and FIFO job queue adapter."""

import asyncio

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.ports.queue import JobQueuePort


class InMemoryJobQueueAdapter(JobQueuePort):
    """In-memory thread-safe FIFO job queue adapter."""

    def __init__(self) -> None:
        self._queue: list[JobSpec] = []
        self._lock = asyncio.Lock()

    async def enqueue(self, job: JobSpec) -> None:
        """Enqueue job in FIFO sequence."""
        async with self._lock:
            self._queue.append(job)

    async def dequeue(self, timeout_seconds: float = 1.0) -> JobSpec | None:
        """Dequeue the next available job."""
        async with self._lock:
            if not self._queue:
                return None
            return self._queue.pop(0)

    async def peek(self, limit: int = 10) -> list[JobSpec]:
        """Peek queued jobs."""
        async with self._lock:
            return list(self._queue[:limit])

    async def remove(self, job_id: str) -> bool:
        """Remove a job by ID."""
        async with self._lock:
            initial_len = len(self._queue)
            self._queue = [j for j in self._queue if j.id != job_id]
            return len(self._queue) < initial_len

    async def size(self) -> int:
        """Return number of queued jobs."""
        async with self._lock:
            return len(self._queue)


__all__ = [
    "InMemoryJobQueueAdapter",
]
