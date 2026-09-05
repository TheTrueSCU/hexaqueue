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
        """Yield log chunks for a given job."""
        chunks = self._logs.get(job_id, [])
        if tail:
            chunks = chunks[-tail:]
        for chunk in chunks:
            yield chunk


__all__ = [
    "InMemoryLogStreamAdapter",
]
