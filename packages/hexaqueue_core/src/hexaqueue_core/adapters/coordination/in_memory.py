"""In-memory coordinator and leader election adapter.

Notes/Architectural Intent:
    Provides thread-safe and asyncio-safe leader lease coordination using
    UTC expiration deadlines and mutual exclusion for local or single-process
    failover testing.
"""

import asyncio
from datetime import UTC, datetime, timedelta

from hexaqueue_core.domain.coordination import LeaderLease
from hexaqueue_core.ports.coordination import LeaderElectionPort


class InMemoryLeaderElectionAdapter(LeaderElectionPort):
    """In-memory distributed leader election implementation."""

    def __init__(self) -> None:
        """Initialize in-memory coordinator with an empty lease and lock."""
        self._current_lease: LeaderLease | None = None
        self._lock = asyncio.Lock()

    async def acquire_leadership(
        self,
        candidate_id: str,
        lease_duration_seconds: float,
    ) -> bool:
        """Attempt to acquire active leadership for the specified candidate.

        Args:
            candidate_id: Unique candidate controller identifier.
            lease_duration_seconds: Validity duration in seconds.

        Returns:
            True if leadership was acquired, False if held by another active candidate.
        """
        async with self._lock:
            now = datetime.now(UTC)
            if self._current_lease is not None and not self._current_lease.is_expired(
                now
            ):
                if self._current_lease.leader_id == candidate_id:
                    self._current_lease = self._current_lease.renew(
                        lease_duration_seconds
                    )
                    return True
                return False

            expires = now + timedelta(seconds=lease_duration_seconds)
            self._current_lease = LeaderLease(
                acquired_at=now,
                expires_at=expires,
                leader_id=candidate_id,
                lease_duration_seconds=lease_duration_seconds,
            )
            return True

    async def renew_leadership(
        self,
        candidate_id: str,
        lease_duration_seconds: float,
    ) -> bool:
        """Renew leadership lease if currently held by candidate.

        Args:
            candidate_id: Candidate identifier requesting renewal.
            lease_duration_seconds: Duration in seconds to extend.

        Returns:
            True if lease was renewed, False if candidate is not the active leader.
        """
        async with self._lock:
            now = datetime.now(UTC)
            if (
                self._current_lease is None
                or self._current_lease.is_expired(now)
                or self._current_lease.leader_id != candidate_id
            ):
                return False

            self._current_lease = self._current_lease.renew(lease_duration_seconds)
            return True

    async def release_leadership(self, candidate_id: str) -> None:
        """Release active leadership held by candidate.

        Args:
            candidate_id: Candidate identifier releasing leadership.
        """
        async with self._lock:
            if (
                self._current_lease is not None
                and self._current_lease.leader_id == candidate_id
            ):
                self._current_lease = None

    async def get_current_leader(self) -> LeaderLease | None:
        """Retrieve active leadership lease if unexpired.

        Returns:
            Active LeaderLease, or None if no leader or lease expired.
        """
        async with self._lock:
            now = datetime.now(UTC)
            if self._current_lease is not None and self._current_lease.is_expired(now):
                self._current_lease = None
            return self._current_lease

    async def is_leader(self, candidate_id: str) -> bool:
        """Check whether candidate currently holds leadership.

        Args:
            candidate_id: Candidate identifier to query.

        Returns:
            True if candidate is the unexpired leader, False otherwise.
        """
        active_lease = await self.get_current_leader()
        return active_lease is not None and active_lease.leader_id == candidate_id


__all__ = [
    "InMemoryLeaderElectionAdapter",
]
