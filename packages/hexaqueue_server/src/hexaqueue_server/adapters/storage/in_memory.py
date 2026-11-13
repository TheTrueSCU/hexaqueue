"""In-memory reference oracle implementation of SchedulerStoragePort.

Notes/Architectural Intent:
    Serves as the high-speed local test double and reference oracle for Dual-Implementation
    Oracle testing (ADR-004), validating database storage adapters against a simple,
    provably correct dictionary and list implementation.
"""

from collections.abc import Sequence

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_core.domain.telemetry import NodeTelemetryPulse
from hexaqueue_server.domain.models import RunStatusReport
from hexaqueue_server.ports.storage import SchedulerStoragePort

__all__ = [
    "InMemorySchedulerStorageAdapter",
]


class InMemorySchedulerStorageAdapter(SchedulerStoragePort):
    """In-memory reference storage adapter for scheduler history and telemetry.

    Notes/Architectural Intent:
        Stores runs, jobs, node profiles, and telemetry pulses in volatile memory.
        Used for hermetic testing and dual-oracle property fuzzing.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory collections."""
        self._runs: dict[str, RunStatusReport] = {}
        self._jobs: dict[str, JobSpec] = {}
        self._nodes: dict[str, ComputeNodeProfile] = {}
        self._telemetry: list[NodeTelemetryPulse] = []

    async def record_run(self, run: RunStatusReport) -> None:
        """Persist or update a pipeline run status record.

        Args:
            run: Run status report instance.
        """
        run_key = run.id or run.run_id
        self._runs[run_key] = run

    async def get_run(self, run_id: str) -> RunStatusReport | None:
        """Retrieve a pipeline run status record by identifier.

        Args:
            run_id: Unique pipeline run identifier.

        Returns:
            RunStatusReport instance if found, None otherwise.
        """
        return self._runs.get(run_id)

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
        sorted_runs = sorted(
            self._runs.values(),
            key=lambda r: r.created_at,
            reverse=True,
        )
        return sorted_runs[offset : offset + limit]

    async def record_job(self, job: JobSpec) -> None:
        """Persist or update an individual job specification record.

        Args:
            job: Job specification instance.
        """
        self._jobs[job.id] = job

    async def get_job(self, job_id: str) -> JobSpec | None:
        """Retrieve a job specification by unique job identifier.

        Args:
            job_id: Unique job identifier.

        Returns:
            JobSpec instance if found, None otherwise.
        """
        return self._jobs.get(job_id)

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
        candidates = list(self._jobs.values())
        if run_id is not None:
            candidates = [j for j in candidates if j.run_id == run_id]

        sorted_jobs = sorted(
            candidates,
            key=lambda j: j.created_at,
            reverse=True,
        )
        return sorted_jobs[offset : offset + limit]

    async def record_node(self, node: ComputeNodeProfile) -> None:
        """Persist or update a compute worker node profile.

        Args:
            node: Compute node profile instance.
        """
        self._nodes[node.node_id] = node

    async def get_node(self, node_id: str) -> ComputeNodeProfile | None:
        """Retrieve a compute worker node profile by identifier.

        Args:
            node_id: Unique compute node identifier.

        Returns:
            ComputeNodeProfile instance if found, None otherwise.
        """
        return self._nodes.get(node_id)

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
        sorted_nodes = sorted(
            self._nodes.values(),
            key=lambda n: n.last_heartbeat_at,
            reverse=True,
        )
        return sorted_nodes[offset : offset + limit]

    async def record_telemetry_pulse(self, pulse: NodeTelemetryPulse) -> None:
        """Persist a periodic worker telemetry pulse snapshot.

        Args:
            pulse: Worker node telemetry pulse instance.
        """
        self._telemetry.append(pulse)

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
        candidates = self._telemetry
        if worker_id is not None:
            candidates = [p for p in candidates if p.worker_id == worker_id]

        sorted_pulses = sorted(
            candidates,
            key=lambda p: p.timestamp,
            reverse=True,
        )
        return sorted_pulses[offset : offset + limit]

    async def flush(self) -> None:
        """Flush any pending buffered write-behind records to durable storage."""

    async def close(self) -> None:
        """Close database connections and terminate background write workers."""
