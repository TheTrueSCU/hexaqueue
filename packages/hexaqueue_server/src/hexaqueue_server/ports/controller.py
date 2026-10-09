"""Scheduler controller port interface."""

from abc import ABC, abstractmethod

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_core.domain.retry import DeadLetterRecord
from hexaqueue_core.domain.telemetry import NodeTelemetryPulse
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_server.domain.placement import PlacementDecision


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
        walltime_seconds: float | None = None,
        consumed_credits: float | None = None,
    ) -> None:
        """Record the terminal outcome of an executed job and advance dependent downstream tasks.

        Args:
            job_id: Finished job identifier.
            outcome: Final TerminalOutcome (COMPLETED, FAILED, TIMED_OUT, CANCELLED).
            reason: Optional explanation or error message.
            walltime_seconds: Optional executed walltime in seconds for budget accounting.
            consumed_credits: Optional exact consumed credits for budget accounting.
        """

    @abstractmethod
    async def cancel_run(self, run_id: str) -> RunStatusReport:
        """Cancel an in-flight run and all of its remaining non-terminal jobs.

        Args:
            run_id: Pipeline run identifier to cancel.

        Returns:
            Updated RunStatusReport showing CANCELLED state.
        """

    @abstractmethod
    async def list_jobs(self) -> list[JobSpec]:
        """Retrieve all currently registered jobs across runs.

        Returns:
            List of all JobSpec instances.
        """

    @abstractmethod
    async def cancel_job(self, job_id: str) -> JobSpec:
        """Cancel an individual job.

        Args:
            job_id: Unique job identifier.

        Returns:
            Updated JobSpec with CANCELLED outcome.
        """

    @abstractmethod
    async def hold_job(self, job_id: str) -> JobSpec:
        """Place an administrative hold on a job.

        Args:
            job_id: Unique job identifier.

        Returns:
            Updated JobSpec in BLOCKED state.
        """

    @abstractmethod
    async def release_job(self, job_id: str) -> JobSpec:
        """Release an administrative hold on a job.

        Args:
            job_id: Unique job identifier.

        Returns:
            Updated JobSpec returned to PENDING or appropriate state.
        """

    @abstractmethod
    async def register_node(self, profile: ComputeNodeProfile) -> None:
        """Register a compute worker node with the central controller.

        Args:
            profile: Initial compute node profile and resource capacity.
        """

    @abstractmethod
    async def heartbeat_node(
        self,
        worker_id: str,
        active_job_ids: list[str] | None = None,
        cached_collateral_hashes: list[str] | None = None,
        pulse: NodeTelemetryPulse | None = None,
    ) -> ComputeNodeProfile:
        """Record a heartbeat pulse from a compute worker node.

        Args:
            worker_id: Unique worker node identifier.
            active_job_ids: Optional list of in-flight job IDs on the worker.
            cached_collateral_hashes: Optional list of CAS hashes present in node's local disk cache.
            pulse: Optional telemetry pulse emitted by the worker node.

        Returns:
            Updated ComputeNodeProfile instance.

        Raises:
            HexaqueueError: If worker_id is not registered.
        """

    @abstractmethod
    async def list_nodes(self) -> list[ComputeNodeProfile]:
        """Retrieve all currently registered compute worker nodes.

        Returns:
            List of ComputeNodeProfile instances.
        """

    @abstractmethod
    async def evaluate_node_failures(
        self,
        timeout_unhealthy_seconds: float = 15.0,
        timeout_dead_seconds: float = 30.0,
    ) -> list[ComputeNodeProfile]:
        """Audit heartbeat recency, mark degraded nodes, and evict/recover jobs from dead nodes.

        Args:
            timeout_unhealthy_seconds: Missed pulse threshold before marking UNHEALTHY.
            timeout_dead_seconds: Missed pulse threshold before marking DEAD and evicting.

        Returns:
            List of newly declared DEAD or DRAINED ComputeNodeProfile instances.
        """

    @abstractmethod
    async def list_dead_letters(self, limit: int = 50) -> list[DeadLetterRecord]:
        """Retrieve preserved dead-lettered job failure records.

        Args:
            limit: Maximum count of dead-letter records to return.

        Returns:
            List of DeadLetterRecord entries.
        """

    @abstractmethod
    async def schedule_placement(
        self,
        job_id: str,
        collateral_hash_map: dict[str, str] | None = None,
    ) -> PlacementDecision:
        """Evaluate and assign an optimal compute worker node for a pending job.

        Args:
            job_id: Unique job identifier.
            collateral_hash_map: Optional mapping of collateral IDs to CAS hashes.

        Returns:
            PlacementDecision containing selected node or auto-scaling burst recommendation.

        Raises:
            HexaqueueError: If job is not found or controller is in standby mode.
        """


__all__ = [
    "SchedulerControllerPort",
]
