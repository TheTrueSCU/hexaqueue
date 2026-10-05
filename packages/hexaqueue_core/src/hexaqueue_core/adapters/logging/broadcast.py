"""Broadcast log streaming adapter supporting live subscription and historical buffering.

Notes/Architectural Intent:
    Provides a real-time pub/sub distribution mechanism for job stdout/stderr logs.
    Decouples executing tasks from live observers (`hq logs -f`, WebSocket dash clients)
    using bounded ring buffers and asynchronous subscriber queues to guarantee zero
    blocking or backpressure stalling on the compute worker.
"""

import asyncio
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from typing import Final

from hexaqueue_core.ports.logging import LogChunk, LogStreamPort

DEFAULT_HISTORY_LIMIT: Final[int] = 5000
DEFAULT_SUBSCRIBER_QUEUE_SIZE: Final[int] = 1000


class BroadcastLogStreamAdapter(LogStreamPort):
    """Asynchronous broadcasting log stream adapter with ring buffer history.

    Args:
        history_limit: Maximum historical log chunks to retain per job.
        subscriber_queue_size: Capacity of per-subscriber asynchronous queue before dropping.

    Notes/Architectural Intent:
        Employs bounded subscriber queues to prevent slow observers from consuming unbounded
        worker memory or stalling worker stdout pipelines.
    """

    def __init__(
        self,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        subscriber_queue_size: int = DEFAULT_SUBSCRIBER_QUEUE_SIZE,
    ) -> None:
        self._history_limit = history_limit
        self._subscriber_queue_size = subscriber_queue_size
        self._history: dict[str, deque[LogChunk]] = defaultdict(
            lambda: deque(maxlen=self._history_limit)
        )
        self._subscribers: dict[str, set[asyncio.Queue[LogChunk | None]]] = defaultdict(
            set
        )
        self._closed_streams: set[str] = set()
        self._lock = asyncio.Lock()

    async def write_log(self, chunk: LogChunk) -> None:
        """Append a log chunk to history and broadcast to active subscribers.

        Args:
            chunk: LogChunk to append and broadcast.

        Notes/Architectural Intent:
            Uses non-blocking put with exception suppression so slow consumer queues
            cannot block or crash the process logging stream.
        """
        job_id = chunk.job_id
        async with self._lock:
            self._history[job_id].append(chunk)
            subscribers = set(self._subscribers.get(job_id, set()))

        for sub_queue in subscribers:
            try:
                sub_queue.put_nowait(chunk)
            except asyncio.QueueFull:
                # Discard oldest chunk or skip to prevent backpressure blocking
                try:
                    _ = sub_queue.get_nowait()
                    sub_queue.put_nowait(chunk)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    async def stream_logs(
        self, job_id: str, follow: bool = False, tail: int | None = None
    ) -> AsyncIterator[LogChunk]:
        """Stream log chunks for a given job, optionally tailing live output.

        Args:
            job_id: Unique job identifier to query.
            follow: If True, keep stream open and yield incoming chunks until stream closes.
            tail: Optional limit for initial historical chunks.

        Yields:
            LogChunk items in chronological order.

        Notes/Architectural Intent:
            First yields buffered history up to `tail` limit, then transparently transitions
            to live subscription if `follow=True`.
        """
        async with self._lock:
            history_list = list(self._history.get(job_id, deque()))
            is_closed = job_id in self._closed_streams

        if tail is not None and tail > 0:
            history_list = history_list[-tail:]

        for chunk in history_list:
            yield chunk

        if not follow or is_closed:
            return

        sub_queue: asyncio.Queue[LogChunk | None] = asyncio.Queue(
            maxsize=self._subscriber_queue_size
        )
        async with self._lock:
            if job_id in self._closed_streams:
                return
            self._subscribers[job_id].add(sub_queue)

        try:
            while True:
                live_chunk = await sub_queue.get()
                if live_chunk is None:
                    break
                yield live_chunk
        finally:
            async with self._lock:
                self._subscribers[job_id].discard(sub_queue)
                if not self._subscribers[job_id]:
                    self._subscribers.pop(job_id, None)

    async def close_stream(self, job_id: str) -> None:
        """Signal that the active log stream for a job is closed.

        Args:
            job_id: Job identifier whose stream has completed.

        Notes/Architectural Intent:
            Broadcasts a sentinel `None` to all active live subscribers to terminate
            their async iteration cleanly.
        """
        async with self._lock:
            self._closed_streams.add(job_id)
            subscribers = set(self._subscribers.pop(job_id, set()))

        for sub_queue in subscribers:
            try:
                sub_queue.put_nowait(None)
            except asyncio.QueueFull:
                try:
                    _ = sub_queue.get_nowait()
                    sub_queue.put_nowait(None)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass


__all__ = [
    "BroadcastLogStreamAdapter",
    "DEFAULT_HISTORY_LIMIT",
    "DEFAULT_SUBSCRIBER_QUEUE_SIZE",
]
