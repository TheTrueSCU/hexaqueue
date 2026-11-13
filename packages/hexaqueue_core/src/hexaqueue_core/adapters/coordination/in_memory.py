"""In-memory coordinator and leader election adapter.

Notes/Architectural Intent:
    Provides thread-safe and asyncio-safe leader lease coordination using
    UTC expiration deadlines and mutual exclusion for local or single-process
    failover testing, including on_elected and on_deposed event notifications.
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
        lease_duration_seconds: float = 15.0,
    ) -> bool:
        """Attempt to acquire active leadership for the specified candidate.

        Args:
            candidate_id: Unique candidate controller identifier.
            lease_duration_seconds: Validity duration in seconds.

        Returns:
            True if leadership was acquired, False if held by another active candidate.
        """
        previous_expired_leader: str | None = None
        newly_elected = False

        async with self._lock:
            now = datetime.now(UTC)
            if self._current_lease is not None:
                if not self._current_lease.is_expired(now):
                    if self._current_lease.leader_id == candidate_id:
                        self._current_lease = self._current_lease.renew(
                            lease_duration_seconds
                        )
                        return True
                    return False
                if self._current_lease.leader_id != candidate_id:
                    previous_expired_leader = self._current_lease.leader_id

            expires = now + timedelta(seconds=lease_duration_seconds)
            self._current_lease = LeaderLease(
                acquired_at=now,
                expires_at=expires,
                leader_id=candidate_id,
                lease_duration_seconds=lease_duration_seconds,
            )
            newly_elected = True

        if previous_expired_leader is not None:
            await self._notify_deposed(previous_expired_leader)
        if newly_elected:
            await self._notify_elected(candidate_id)
        return True

    async def renew_leadership(
        self,
        candidate_id: str,
        lease_duration_seconds: float = 15.0,
    ) -> bool:
        """Renew leadership lease if currently held by candidate.

        Args:
            candidate_id: Candidate identifier requesting renewal.
            lease_duration_seconds: Duration in seconds to extend.

        Returns:
            True if lease was renewed, False if candidate is not the active leader.
        """
        deposed_leader: str | None = None
        async with self._lock:
            now = datetime.now(UTC)
            if self._current_lease is None:
                return False
            if self._current_lease.is_expired(now):
                if self._current_lease.leader_id == candidate_id:
                    deposed_leader = candidate_id
                self._current_lease = None
                if deposed_leader is not None:
                    await self._notify_deposed(deposed_leader)
                return False
            if self._current_lease.leader_id != candidate_id:
                return False

            self._current_lease = self._current_lease.renew(lease_duration_seconds)
            return True

    async def release_leadership(self, candidate_id: str) -> None:
        """Release active leadership held by candidate.

        Args:
            candidate_id: Candidate identifier releasing leadership.
        """
        released = False
        async with self._lock:
            if (
                self._current_lease is not None
                and self._current_lease.leader_id == candidate_id
            ):
                self._current_lease = None
                released = True

        if released:
            await self._notify_deposed(candidate_id)

    async def get_current_leader(self) -> LeaderLease | None:
        """Retrieve active leadership lease if unexpired.

        Returns:
            Active LeaderLease, or None if no leader or lease expired.
        """
        expired_leader: str | None = None
        async with self._lock:
            now = datetime.now(UTC)
            if self._current_lease is not None and self._current_lease.is_expired(now):
                expired_leader = self._current_lease.leader_id
                self._current_lease = None
            lease = self._current_lease

        if expired_leader is not None:
            await self._notify_deposed(expired_leader)
        return lease

    async def is_leader(self, candidate_id: str) -> bool:
        """Check whether candidate currently holds leadership.

        Args:
            candidate_id: Candidate identifier to query.

        Returns:
            True if candidate is the unexpired leader, False otherwise.
        """
        active_lease = await self.get_current_leader()
        return active_lease is not None and active_lease.leader_id == candidate_id


InMemoryLeaderAdapter = InMemoryLeaderElectionAdapter

__all__ = [
    "InMemoryLeaderAdapter",
    "InMemoryLeaderElectionAdapter",
]
