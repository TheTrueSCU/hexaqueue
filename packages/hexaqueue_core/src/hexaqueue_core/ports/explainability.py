"""Port definitions for scheduler explainability and decision inspection.

Notes/Architectural Intent:
    Defines the abstract interface for querying scheduler diagnostics, priority
    breakdowns, and fair-share hierarchies. Driving adapters (CLI, gRPC, REST,
    Dashboard) interact exclusively through this port.
"""

from abc import ABC, abstractmethod

from hexaqueue_core.domain.explainability import (
    FairShareTreeReport,
    SchedulingDecisionReport,
)


class SchedulerExplainabilityPort(ABC):
    """Abstract port for scheduler explainability and fair-share diagnostics.

    Notes/Architectural Intent:
        Enforces tenant authorization and privacy filters across all diagnostic
        inquiries, ensuring clean hexagonal boundaries.
    """

    @abstractmethod
    def explain_job(
        self,
        job_id: str,
        requesting_user: str,
        is_admin: bool = False,
    ) -> SchedulingDecisionReport:
        """Retrieve diagnostic scheduling explanation for a given job.

        Args:
            job_id: Identifier of target job.
            requesting_user: User initiating inquiry for privacy scoping.
            is_admin: Whether requester has administrative privileges.

        Returns:
            SchedulingDecisionReport detailing priority math, rank, and blockers.
        """
        ...

    @abstractmethod
    def explain_fairshare(
        self,
        requesting_user: str,
        is_admin: bool = False,
    ) -> FairShareTreeReport:
        """Retrieve hierarchical fair-share tree diagnostic report.

        Args:
            requesting_user: User initiating inquiry for privacy scoping.
            is_admin: Whether requester has administrative privileges.

        Returns:
            FairShareTreeReport detailing tree structure and decay status.
        """
        ...


__all__ = [
    "SchedulerExplainabilityPort",
]
