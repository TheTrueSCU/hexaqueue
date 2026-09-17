"""Client port interface for CLI command dispatching.

Notes/Architectural Intent:
    Decouples CLI commands from transport (direct in-process vs gRPC/HTTP daemon).
"""

from abc import ABC, abstractmethod

from hexaqueue_core.domain.explainability import (
    FairShareTreeReport,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission


class ClientPort(ABC):
    """Abstract client interface for CLI commands."""

    @abstractmethod
    async def submit_run(self, submission: RunSubmission) -> RunStatusReport:
        """Submit a pipeline run."""

    @abstractmethod
    async def get_run_status(self, run_id: str) -> RunStatusReport:
        """Get aggregate run status."""

    @abstractmethod
    async def get_job(self, job_id: str) -> JobSpec:
        """Get individual job status."""

    @abstractmethod
    async def cancel_run(self, run_id: str) -> RunStatusReport:
        """Cancel a pipeline run."""

    @abstractmethod
    async def get_logs(self, job_id: str) -> list[LogChunk]:
        """Retrieve historical logs for a job."""

    @abstractmethod
    async def explain_job(
        self,
        job_id: str,
        requesting_user: str = "default",
        is_admin: bool = False,
    ) -> SchedulingDecisionReport:
        """Retrieve diagnostic scheduling explanation for a given job."""

    @abstractmethod
    async def get_fairshare_tree(
        self,
        requesting_user: str = "default",
        is_admin: bool = False,
    ) -> FairShareTreeReport:
        """Retrieve hierarchical fair-share tree diagnostic report."""


__all__ = [
    "ClientPort",
]
