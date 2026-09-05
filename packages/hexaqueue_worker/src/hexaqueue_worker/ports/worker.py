"""Worker daemon port interface.

Notes/Architectural Intent:
    Defines the contract for worker daemons managing task polling, isolated workspace provisioning,
    command execution via ExecutionRuntimePort, and outcome notification to SchedulerControllerPort.
"""

from abc import ABC, abstractmethod

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.ports.runtime import ProcessExecutionResult
from hexaqueue_worker.domain.models import WorkerMetrics


class WorkerDaemonPort(ABC):
    """Abstract port interface for worker compute daemons."""

    @abstractmethod
    async def start(self) -> None:
        """Start worker loop pulling and executing jobs."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop worker loop and await in-flight tasks."""

    @abstractmethod
    async def execute_job(self, job: JobSpec) -> ProcessExecutionResult:
        """Execute a single job within isolated scratch storage and report status.

        Args:
            job: JobSpec to execute.

        Returns:
            ProcessExecutionResult summarizing execution outcome.
        """

    @abstractmethod
    async def get_metrics(self) -> WorkerMetrics:
        """Retrieve real-time operational worker metrics.

        Returns:
            WorkerMetrics instance.
        """


__all__ = [
    "WorkerDaemonPort",
]
