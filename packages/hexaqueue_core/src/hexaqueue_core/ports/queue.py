"""Job queue port interface for scheduling and task distribution.

Notes/Architectural Intent:
    Decouples task enqueueing, priority indexing, lease acquisition, and
    heartbeat acknowledgement from underlying transport (In-Memory, Redis, NATS, Etcd).
"""

from abc import ABC, abstractmethod
from hexaqueue_core.domain.job import JobSpec


class JobQueuePort(ABC):
    """Abstract port interface for job queue operations."""

    @abstractmethod
    async def enqueue(self, job: JobSpec) -> None:
        """Enqueue a job for scheduling.

        Args:
            job: The JobSpec to place in the queue.
        """

    @abstractmethod
    async def dequeue(self, timeout_seconds: float = 1.0) -> JobSpec | None:
        """Dequeue the next highest priority eligible job.

        Args:
            timeout_seconds: Maximum time to wait for a job before returning None.

        Returns:
            The highest priority JobSpec, or None if the queue is empty.
        """

    @abstractmethod
    async def peek(self, limit: int = 10) -> list[JobSpec]:
        """Peek at currently queued jobs without dequeuing them.

        Args:
            limit: Maximum number of jobs to inspect.

        Returns:
            List of queued JobSpecs ordered by scheduling priority.
        """

    @abstractmethod
    async def remove(self, job_id: str) -> bool:
        """Remove a job from the queue (e.g. on cancellation).

        Args:
            job_id: Identifier of the job to cancel and remove.

        Returns:
            True if the job was found and removed, False otherwise.
        """

    @abstractmethod
    async def size(self) -> int:
        """Return the number of jobs currently waiting in the queue.

        Returns:
            Total queued jobs count.
        """
