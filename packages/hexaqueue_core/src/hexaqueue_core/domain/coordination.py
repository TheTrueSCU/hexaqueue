"""Distributed leader election and lease coordination domain models.

Notes/Architectural Intent:
    Defines time-bounded leader leases and event-loop-agnostic async concurrency
    primitives (`CrossLoopAsyncLock`, `CrossLoopAsyncCondition`) used by active/standby
    central controllers and slice coordinators to synchronize state across concurrent
    worker threads and asyncio event loops without loop-binding errors.
"""

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CrossLoopAsyncLock:
    """Event-loop-agnostic async mutex safe across multiple event loops and threads.

    Notes/Architectural Intent:
        Standard library `asyncio.Lock` inherits from `_LoopBoundMixin`, which permanently
        binds `_loop` to the first event loop that experiences lock contention. When
        synchronous CQRS buses (`run_coro_sync`) and asynchronous FastAPI/Uvicorn routes
        interact with shared singleton adapters, a loop-bound lock raises
        `RuntimeError: <Lock> is bound to a different event loop`. `CrossLoopAsyncLock`
        uses a non-reentrant `threading.Lock` with cooperative async polling so it never
        binds to any single event loop.
    """

    def __init__(self) -> None:
        self._mutex = threading.Lock()

    def locked(self) -> bool:
        """Return True if the mutex is currently held.

        Returns:
            True if locked, False otherwise.
        """
        return self._mutex.locked()

    async def acquire(self) -> Literal[True]:
        """Acquire the mutex without blocking the caller's active event loop.

        Returns:
            True once the mutex is acquired.
        """
        while not self._mutex.acquire(blocking=False):
            await asyncio.sleep(0.0005)
        return True

    def release(self) -> None:
        """Release the underlying mutex."""
        self._mutex.release()

    async def __aenter__(self) -> Self:
        """Enter the async context manager by acquiring the mutex.

        Returns:
            Self instance.
        """
        await self.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit the async context manager by releasing the mutex."""
        self.release()


class CrossLoopAsyncCondition:
    """Event-loop-agnostic async condition variable safe across multiple event loops.

    Args:
        lock: Optional underlying `CrossLoopAsyncLock` instance.

    Notes/Architectural Intent:
        Uses a monotonic generation counter paired with `CrossLoopAsyncLock` so that
        `notify_all()` / `notify()` called from a synchronous CQRS worker thread's event
        loop cleanly wakes `wait()` coroutines suspended on the main ASGI event loop.
    """

    def __init__(self, lock: CrossLoopAsyncLock | None = None) -> None:
        self._lock = lock or CrossLoopAsyncLock()
        self._generation = 0

    async def acquire(self) -> Literal[True]:
        """Acquire the underlying lock.

        Returns:
            True once acquired.
        """
        return await self._lock.acquire()

    def release(self) -> None:
        """Release the underlying lock."""
        self._lock.release()

    def notify_all(self) -> None:
        """Wake all coroutines waiting on this condition across any event loop."""
        self._generation += 1

    def notify(self, n: int = 1) -> None:
        """Wake waiting coroutines by advancing the condition generation.

        Args:
            n: Number of waiters to wake (positive values advance generation).
        """
        if n > 0:
            self._generation += 1

    async def wait(self) -> Literal[True]:
        """Release the lock, wait until notified on any loop, and re-acquire the lock.

        Returns:
            True once awakened and lock is re-acquired.
        """
        gen = self._generation
        self._lock.release()
        try:
            while self._generation == gen:
                await asyncio.sleep(0.002)
        finally:
            await self._lock.acquire()
        return True

    async def __aenter__(self) -> Self:
        """Acquire the condition lock on context entry.

        Returns:
            Self instance.
        """
        await self._lock.acquire()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Release the condition lock on context exit."""
        self._lock.release()


class LeaderLease(BaseModel):
    """Time-bounded lease granting exclusive active leadership to a controller.

    Args:
        leader_id: Unique candidate or node identifier holding the lease.
        lease_duration_seconds: Duration in seconds for which the lease is valid.
        acquired_at: Timestamp in UTC when leadership was initially acquired.
        expires_at: Timestamp in UTC after which the lease is considered expired.
        renewal_count: Number of successful heartbeat renewals performed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    acquired_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Lease acquisition timestamp in UTC",
    )
    expires_at: datetime = Field(description="Lease expiration timestamp in UTC")
    leader_id: str = Field(description="Active leader identifier")
    lease_duration_seconds: float = Field(
        gt=0.0, description="Lease validity duration in seconds"
    )
    renewal_count: int = Field(
        default=0, ge=0, description="Number of heartbeat renewals"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate required identifier fields and expiration ordering.

        Returns:
            The validated LeaderLease instance.

        Raises:
            ValueError: If leader_id is blank or expires_at is before acquired_at.
        """
        if not self.leader_id.strip():
            msg = "leader_id cannot be empty"
            raise ValueError(msg)
        if self.expires_at < self.acquired_at:
            msg = f"expires_at ({self.expires_at}) cannot precede acquired_at ({self.acquired_at})"
            raise ValueError(msg)
        return self

    def is_expired(self, now: datetime | None = None) -> bool:
        """Check whether the lease has passed its expiration deadline.

        Args:
            now: Optional point-in-time timestamp (defaults to current UTC time).

        Returns:
            True if the lease is expired, False otherwise.
        """
        current_time = now or datetime.now(UTC)
        return current_time >= self.expires_at

    def renew(self, duration_seconds: float | None = None) -> Self:
        """Extend the lease expiration by the specified or existing duration.

        Args:
            duration_seconds: Optional new validity duration in seconds.

        Returns:
            Updated LeaderLease instance with extended expiration.
        """
        now = datetime.now(UTC)
        duration = duration_seconds or self.lease_duration_seconds
        new_expires = now + timedelta(seconds=duration)
        return self.model_copy(
            update={
                "expires_at": new_expires,
                "lease_duration_seconds": duration,
                "renewal_count": self.renewal_count + 1,
            }
        )


__all__ = [
    "CrossLoopAsyncCondition",
    "CrossLoopAsyncLock",
    "LeaderLease",
]
