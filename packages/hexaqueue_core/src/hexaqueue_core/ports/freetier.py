"""Hexagonal port interface for CSP Free-Tier governance and quota clamping.

Notes/Architectural Intent:
    Defines the contract for intercepting job submissions, placement requests,
    and cluster capacity allocations under Free-Tier Safety Mode.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.freetier import (
    CspFreeTierProfile,
    FederatedBurnReport,
    FederatedFreeTierMesh,
    FreeTierBurnReport,
    MultiCspPlacementCandidate,
)
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


class FederatedFreeTierGovernorPort(ABC):
    """Abstract port interface for Multi-CSP Free-Tier mesh quota governance.

    Notes/Architectural Intent:
        Orchestrates multi-cloud resource reservation, dynamic provider placement,
        and zero-cost spend clamping across heterogeneous cloud Always-Free tiers.
    """

    @property
    @abstractmethod
    def mesh(self) -> FederatedFreeTierMesh:
        """Retrieve active federated free-tier mesh.

        Returns:
            FederatedFreeTierMesh specification.
        """
        raise NotImplementedError

    @abstractmethod
    def allocate_job(
        self, job: JobSpec, preferred_provider: CspProvider | None = None
    ) -> CspProvider:
        """Reserve free-tier capacity for a job on an eligible CSP.

        Args:
            job: Candidate JobSpec requesting compute slots.
            preferred_provider: Optional preferred CSP.

        Returns:
            Assigned CspProvider where the job has been allocated.

        Raises:
            FreeTierLimitExceededError: If the job exceeds individual provider limits
                or no provider has sufficient headroom.
        """
        raise NotImplementedError

    @abstractmethod
    def release_job(self, job_id: str) -> None:
        """Release allocated free-tier capacity held by a job.

        Args:
            job_id: Unique job identifier to deallocate.
        """
        raise NotImplementedError

    @abstractmethod
    def find_eligible_provider(
        self, job: JobSpec, preferred_provider: CspProvider | None = None
    ) -> MultiCspPlacementCandidate:
        """Evaluate provider candidates to find the best-fit free-tier provider.

        Args:
            job: Candidate JobSpec to evaluate.
            preferred_provider: Optional preferred CSP.

        Returns:
            MultiCspPlacementCandidate containing placement verdict and metrics.
        """
        raise NotImplementedError

    @abstractmethod
    def check_headroom(self, job: JobSpec) -> bool:
        """Check whether any participating CSP in the mesh has available headroom.

        Args:
            job: Candidate JobSpec awaiting dispatch.

        Returns:
            True if at least one CSP can host the job without exceeding free caps.
        """
        raise NotImplementedError

    @abstractmethod
    def compute_federated_burn_meter(self) -> FederatedBurnReport:
        """Compute real-time multi-CSP aggregated burn meter and quota utilization.

        Returns:
            FederatedBurnReport snapshot aggregating all participating CSPs.
        """
        raise NotImplementedError


__all__ = [
    "FederatedFreeTierGovernorPort",
    "FreeTierGovernorPort",
]
