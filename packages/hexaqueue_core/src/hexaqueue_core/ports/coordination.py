"""Leader election and distributed coordination port interface.

Notes/Architectural Intent:
    Defines the abstract contract for acquiring, renewing, releasing, and inspecting
    central controller leadership leases to eliminate split-brain execution in HA clusters.
    Provides event callbacks (`on_elected`, `on_deposed`) and `renew_lease` alias
    to support active-standby controller lifecycle transitions.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from hexaqueue_core.domain.coordination import LeaderLease

LeaderLifecycleCallback = Callable[[str], None | Awaitable[None]]


class LeaderElectionPort(ABC):
    """Abstract port for distributed leader election and lease coordination.

    Notes/Architectural Intent:
        Implementations guarantee mutual exclusion across candidate controller
        processes via TTL-bounded leases (in-memory, SQL database row locks, or
        Kubernetes coordination.v1.Lease resources) and invoke registered lifecycle
        callbacks when leadership is acquired or lost.
    """

    @abstractmethod
    async def acquire_leadership(
        self,
        candidate_id: str,
        lease_duration_seconds: float = 15.0,
    ) -> bool:
        """Attempt to acquire active leadership for the specified candidate.

        Args:
            candidate_id: Unique identifier of the candidate controller.
            lease_duration_seconds: Duration in seconds for which the acquired lease is valid.

        Returns:
            True if leadership was successfully acquired, False otherwise.
        """

    @abstractmethod
    async def renew_leadership(
        self,
        candidate_id: str,
        lease_duration_seconds: float = 15.0,
    ) -> bool:
        """Renew the active leadership lease for the currently elected leader.

        Args:
            candidate_id: Unique identifier of the candidate requesting renewal.
            lease_duration_seconds: Duration in seconds to extend the lease.

        Returns:
            True if the lease was successfully renewed, False if the candidate is not the leader.
        """

    async def renew_lease(
        self,
        candidate_id: str,
        lease_duration_seconds: float = 15.0,
    ) -> bool:
        """Alias for renew_leadership satisfying standard HA lease terminology.

        Args:
            candidate_id: Unique identifier of the candidate requesting renewal.
            lease_duration_seconds: Duration in seconds to extend the lease.

        Returns:
            True if the lease was renewed, False otherwise.
        """
        return await self.renew_leadership(candidate_id, lease_duration_seconds)

    @abstractmethod
    async def release_leadership(self, candidate_id: str) -> None:
        """Voluntarily release active leadership held by the specified candidate.

        Args:
            candidate_id: Identifier of the leader releasing its lease.
        """

    @abstractmethod
    async def get_current_leader(self) -> LeaderLease | None:
        """Retrieve the currently active leadership lease, if valid.

        Returns:
            Active LeaderLease instance, or None if no valid lease exists or it has expired.
        """

    @abstractmethod
    async def is_leader(self, candidate_id: str) -> bool:
        """Check whether the specified candidate currently holds valid leadership.

        Args:
            candidate_id: Identifier of the candidate to query.

        Returns:
            True if the candidate holds an unexpired lease, False otherwise.
        """

    def on_elected(self, callback: LeaderLifecycleCallback) -> None:
        """Register a callback invoked when a candidate acquires leadership.

        Args:
            callback: Callable accepting the elected `candidate_id`.
        """
        callbacks = getattr(self, "_elected_callbacks", None)
        if callbacks is None:
            callbacks = []
            self._elected_callbacks = callbacks
        callbacks.append(callback)

    def on_deposed(self, callback: LeaderLifecycleCallback) -> None:
        """Register a callback invoked when a candidate loses or releases leadership.

        Args:
            callback: Callable accepting the deposed `candidate_id`.
        """
        callbacks = getattr(self, "_deposed_callbacks", None)
        if callbacks is None:
            callbacks = []
            self._deposed_callbacks = callbacks
        callbacks.append(callback)

    async def _notify_elected(self, candidate_id: str) -> None:
        """Invoke all registered on_elected callbacks."""
        callbacks: list[LeaderLifecycleCallback] = getattr(
            self, "_elected_callbacks", []
        )
        for cb in callbacks:
            res = cb(candidate_id)
            if res is not None and hasattr(res, "__await__"):
                await res

    async def _notify_deposed(self, candidate_id: str) -> None:
        """Invoke all registered on_deposed callbacks."""
        callbacks: list[LeaderLifecycleCallback] = getattr(
            self, "_deposed_callbacks", []
        )
        for cb in callbacks:
            res = cb(candidate_id)
            if res is not None and hasattr(res, "__await__"):
                await res


__all__ = [
    "LeaderElectionPort",
    "LeaderLifecycleCallback",
]
