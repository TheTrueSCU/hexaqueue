"""Scheduler storage port interface for cold-tier durable cluster history and telemetry.

Notes/Architectural Intent:
    Decouples central scheduler controllers from specific cold-tier durable storage
    engines (e.g. Oracle Autonomous Database, PostgreSQL, SQLite, or in-memory test doubles).
    Provides durable persistence for pipeline runs, job specifications, compute node profiles,
    and periodic worker telemetry pulses without polluting domain models.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_core.domain.telemetry import NodeTelemetryPulse
from hexaqueue_server.domain.models import RunStatusReport

__all__ = [
    "SchedulerStoragePort",
]


class SchedulerStoragePort(ABC):
    """Abstract driven port for durable run history, job metadata, and cluster telemetry.

    Notes/Architectural Intent:
        Implementations provide persistence across controller restarts, supporting
        both direct transactional writes and asynchronous write-behind queues.
    """

    @abstractmethod
    async def record_run(self, run: RunStatusReport) -> None:
        """Persist or update a pipeline run status record.

        Args:
            run: Run status report instance.

        Raises:
            HexaqueueError: If persistence encounters an unrecoverable storage failure.
        """

    @abstractmethod
    async def get_run(self, run_id: str) -> RunStatusReport | None:
        """Retrieve a pipeline run status record by identifier.

        Args:
            run_id: Unique pipeline run identifier.

        Returns:
            RunStatusReport instance if found, None otherwise.
        """

    @abstractmethod
    async def list_runs(
        self, limit: int = 100, offset: int = 0
    ) -> Sequence[RunStatusReport]:
        """List historical pipeline run records ordered by creation time descending.

        Args:
            limit: Maximum records to return.
            offset: Number of records to skip.

        Returns:
            Sequence of RunStatusReport instances.
        """

    @abstractmethod
    async def record_job(self, job: JobSpec) -> None:
        """Persist or update an individual job specification record.

        Args:
            job: Job specification instance.

        Raises:
            HexaqueueError: If persistence encounters an unrecoverable storage failure.
        """

    @abstractmethod
    async def get_job(self, job_id: str) -> JobSpec | None:
        """Retrieve a job specification by unique job identifier.

        Args:
            job_id: Unique job identifier.

        Returns:
            JobSpec instance if found, None otherwise.
        """

    @abstractmethod
    async def list_jobs(
        self, run_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> Sequence[JobSpec]:
        """List historical job records optionally filtered by pipeline run.

        Args:
            run_id: Optional pipeline run identifier filter.
            limit: Maximum records to return.
            offset: Number of records to skip.

        Returns:
            Sequence of JobSpec instances.
        """

    @abstractmethod
    async def record_node(self, node: ComputeNodeProfile) -> None:
        """Persist or update a compute worker node profile.

        Args:
            node: Compute node profile instance.

        Raises:
            HexaqueueError: If persistence encounters an unrecoverable storage failure.
        """

    @abstractmethod
    async def get_node(self, node_id: str) -> ComputeNodeProfile | None:
        """Retrieve a compute worker node profile by identifier.

        Args:
            node_id: Unique compute node identifier.

        Returns:
            ComputeNodeProfile instance if found, None otherwise.
        """

    @abstractmethod
    async def list_nodes(
        self, limit: int = 100, offset: int = 0
    ) -> Sequence[ComputeNodeProfile]:
        """List compute worker nodes ordered by last heartbeat descending.

        Args:
            limit: Maximum records to return.
            offset: Number of records to skip.

        Returns:
            Sequence of ComputeNodeProfile instances.
        """

    @abstractmethod
    async def record_telemetry_pulse(self, pulse: NodeTelemetryPulse) -> None:
        """Persist a periodic worker telemetry pulse snapshot.

        Args:
            pulse: Worker node telemetry pulse instance.

        Raises:
            HexaqueueError: If persistence encounters an unrecoverable storage failure.
        """

    @abstractmethod
    async def list_telemetry_pulses(
        self, worker_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> Sequence[NodeTelemetryPulse]:
        """List historical telemetry pulses optionally filtered by worker.

        Args:
            worker_id: Optional worker identifier filter.
            limit: Maximum records to return.
            offset: Number of records to skip.

        Returns:
            Sequence of NodeTelemetryPulse instances.
        """

    @abstractmethod
    async def flush(self) -> None:
        """Flush any pending buffered write-behind records to durable storage.

        Raises:
            HexaqueueError: If flushing fails.
        """

    @abstractmethod
    async def close(self) -> None:
        """Close database connections and terminate background write workers."""
