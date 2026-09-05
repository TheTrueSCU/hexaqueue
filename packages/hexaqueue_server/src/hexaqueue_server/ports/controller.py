"""Scheduler controller port interface."""

from abc import ABC, abstractmethod

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission


class SchedulerControllerPort(ABC):
    """Abstract port for pipeline submission, scheduling coordination, and status reporting."""

    @abstractmethod
    async def submit_run(self, submission: RunSubmission) -> RunStatusReport:
        """Submit a DAG pipeline run for scheduling.

        Args:
            submission: Complete RunSubmission specification.

        Returns:
            Initial RunStatusReport.

        Raises:
            DependencyCycleError: If dependency graph contains cycles.
            HexaqueueError: If submission fails validation.
        """

    @abstractmethod
    async def get_run_status(self, run_id: str) -> RunStatusReport:
        """Retrieve aggregated run status.

        Args:
            run_id: Unique pipeline run identifier.

        Returns:
            Current RunStatusReport.

        Raises:
            HexaqueueError: If run is not found.
        """

    @abstractmethod
    async def get_job(self, job_id: str) -> JobSpec:
        """Retrieve current metadata and status for an individual job.

        Args:
            job_id: Unique job identifier.

        Returns:
            JobSpec instance.

        Raises:
            HexaqueueError: If job is not found.
        """

    @abstractmethod
    async def update_job_outcome(
        self,
        job_id: str,
        outcome: TerminalOutcome,
        reason: str | None = None,
    ) -> None:
        """Record the terminal outcome of an executed job and advance dependent downstream tasks.

        Args:
            job_id: Finished job identifier.
            outcome: Final TerminalOutcome (COMPLETED, FAILED, TIMED_OUT, CANCELLED).
            reason: Optional explanation or error message.
        """

    @abstractmethod
    async def cancel_run(self, run_id: str) -> RunStatusReport:
        """Cancel an in-flight run and all of its remaining non-terminal jobs.

        Args:
            run_id: Pipeline run identifier to cancel.

        Returns:
            Updated RunStatusReport showing CANCELLED state.
        """


__all__ = [
    "SchedulerControllerPort",
]
