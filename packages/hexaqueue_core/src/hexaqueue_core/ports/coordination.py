"""Leader election and distributed coordination port interface.

Notes/Architectural Intent:
    Defines the abstract contract for acquiring, renewing, releasing, and inspecting
    central controller leadership leases to eliminate split-brain execution in HA clusters.
"""

from abc import ABC, abstractmethod

from hexaqueue_core.domain.coordination import LeaderLease


class LeaderElectionPort(ABC):
    """Abstract port for distributed leader election and lease coordination."""

    @abstractmethod
    async def acquire_leadership(
        self,
        candidate_id: str,
        lease_duration_seconds: float,
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
        lease_duration_seconds: float,
    ) -> bool:
        """Renew the active leadership lease for the currently elected leader.

        Args:
            candidate_id: Unique identifier of the candidate requesting renewal.
            lease_duration_seconds: Duration in seconds to extend the lease.

        Returns:
            True if the lease was successfully renewed, False if the candidate is not the leader.
        """

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


__all__ = [
    "LeaderElectionPort",
]
