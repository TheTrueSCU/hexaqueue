"""Hexagonal port interface for CSP Free-Tier governance and quota clamping.

Notes/Architectural Intent:
    Defines the contract for intercepting job submissions, placement requests,
    and cluster capacity allocations under Free-Tier Safety Mode.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from hexaqueue_core.domain.freetier import CspFreeTierProfile, FreeTierBurnReport
from hexaqueue_core.domain.job import JobSpec


class FreeTierGovernorPort(ABC):
    """Abstract port interface for Free-Tier quota governance."""

    @property
    @abstractmethod
    def profile(self) -> CspFreeTierProfile:
        """Retrieve active CSP profile."""
        raise NotImplementedError

    @abstractmethod
    def validate_job_resource_request(self, job: JobSpec) -> None:
        """Validate that a job's resource requirements do not exceed free-tier caps.

        Args:
            job: Candidate JobSpec to evaluate.

        Raises:
            FreeTierLimitExceededError: If the job requests resources exceeding free tier limits.
        """
        raise NotImplementedError

    @abstractmethod
    def validate_region_placement(self, region: str | None) -> None:
        """Validate that target deployment region is eligible for zero-cost execution.

        Args:
            region: Target cloud region string, or None.

        Raises:
            FreeTierLimitExceededError: If target region is outside CSP's Always-Free boundary.
        """
        raise NotImplementedError

    @abstractmethod
    def check_cluster_headroom(
        self, active_jobs: Sequence[JobSpec], candidate: JobSpec
    ) -> bool:
        """Check whether cluster has sufficient free-tier capacity to schedule candidate.

        Args:
            active_jobs: Sequence of currently executing jobs holding resource slots.
            candidate: Candidate JobSpec awaiting dispatch.

        Returns:
            True if candidate can be dispatched without exceeding free tier caps, False otherwise.
        """
        raise NotImplementedError

    @abstractmethod
    def compute_burn_meter(
        self, active_jobs: Sequence[JobSpec], allocated_storage_mb: int = 0
    ) -> FreeTierBurnReport:
        """Compute real-time burn meter and quota utilization metrics.

        Args:
            active_jobs: Sequence of currently executing or pending jobs holding allocations.
            allocated_storage_mb: Current storage usage in MB.

        Returns:
            FreeTierBurnReport snapshot.
        """
        raise NotImplementedError


__all__ = [
    "FreeTierGovernorPort",
]
