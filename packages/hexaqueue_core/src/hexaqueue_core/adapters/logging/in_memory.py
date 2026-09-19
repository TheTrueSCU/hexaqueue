"""In-memory log streaming adapter."""

from collections import defaultdict
from collections.abc import AsyncIterator

from hexaqueue_core.ports.logging import LogChunk, LogStreamPort


class InMemoryLogStreamAdapter(LogStreamPort):
    """In-memory log ring buffer adapter."""

    def __init__(self) -> None:
        self._logs: dict[str, list[LogChunk]] = defaultdict(list)

    async def write_log(self, chunk: LogChunk) -> None:
        """Append log chunk to memory buffer."""
        self._logs[chunk.job_id].append(chunk)

    async def stream_logs(
        self, job_id: str, follow: bool = False, tail: int | None = None
    ) -> AsyncIterator[LogChunk]:
        """Yield log chunks for a given job.

        Args:
            job_id: Unique job identifier.
            follow: Ignored in basic in-memory adapter.
            tail: Optional line limit for historical logs.

        Yields:
            LogChunk items for the target job.
        """
        chunks = self._logs.get(job_id, [])
        if tail:
            chunks = chunks[-tail:]
        for chunk in chunks:
            yield chunk

    async def close_stream(self, job_id: str) -> None:
        """Close log stream for a given job.

        Args:
            job_id: Unique job identifier.

        Notes/Architectural Intent:
            In-memory adapter maintains logs statically; close_stream is a no-op marker.
        """
        _ = job_id


__all__ = [
    "InMemoryLogStreamAdapter",
]
