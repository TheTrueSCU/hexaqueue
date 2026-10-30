"""Scheduler Memento pattern, speculative placement simulation, and DAG rewind models.

Notes/Architectural Intent:
    Encapsulates point-in-time snapshots of cluster controller state to enable
    pure dry-run speculative placement simulations without side effects.
    Also provides DAG run mementos and rewind reports for selective fault recovery.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobStatus
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_core.domain.retry import DeadLetterRecord
from hexaqueue_server.domain.models import RunSubmission
from hexaqueue_server.domain.placement import PlacementDecision


class PlacementSimulationItem(BaseModel):
    """Simulated placement outcome for a candidate job.

    Args:
        job_id: Candidate job identifier.
        decision: Evaluated placement decision.
        would_preempt: List of job IDs that would be preempted to accommodate this job.
        estimated_wait_seconds: Estimated wait time if queued.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: PlacementDecision = Field(description="Evaluated placement decision")
    estimated_wait_seconds: float = Field(
        default=0.0, ge=0.0, description="Estimated wait latency in seconds"
    )
    job_id: str = Field(description="Candidate job identifier")
    would_preempt: list[str] = Field(
        default_factory=list, description="Hypothetically preempted job IDs"
    )


class PlacementSimulationReport(BaseModel):
    """Aggregate report from a dry-run speculative placement simulation.

    Args:
        items: List of individual job placement evaluations.
        all_schedulable: Whether all candidate jobs could be scheduled.
        required_ephemeral_bursts: Count of jobs requiring cloud bursting.
        simulated_at: UTC timestamp when simulation occurred.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    all_schedulable: bool = Field(
        description="Whether all candidate jobs can be accommodated"
    )
    items: list[PlacementSimulationItem] = Field(
        description="Detailed per-job simulation results"
    )
    required_ephemeral_bursts: int = Field(
        ge=0, description="Total jobs needing cloud bursting"
    )
    simulated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Simulation execution timestamp in UTC",
    )


class SchedulerMemento(BaseModel):
    """Immutable memento capturing internal state of the scheduler controller.

    Args:
        runs: Dictionary of registered pipeline runs.
        jobs: Dictionary of registered jobs and lifecycle statuses.
        nodes: Dictionary of compute worker profiles and allocations.
        job_reservations: Active budget reservation tokens per job.
        dead_letters: Preserved dead letter failure records.
        created_at: Memento capture timestamp in UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Snapshot capture timestamp in UTC",
    )
    dead_letters: list[DeadLetterRecord] = Field(
        default_factory=list, description="Dead letter failure records"
    )
    job_reservations: dict[str, str] = Field(
        default_factory=dict, description="Active budget reservation mappings"
    )
    jobs: dict[str, JobSpec] = Field(
        default_factory=dict, description="Job specifications and statuses"
    )
    nodes: dict[str, ComputeNodeProfile] = Field(
        default_factory=dict, description="Worker node profiles"
    )
    runs: dict[str, RunSubmission] = Field(
        default_factory=dict, description="Registered DAG pipeline runs"
    )


class DagRunMemento(BaseModel):
    """Snapshot of DAG run execution outcomes for partial resumption.

    Args:
        run_id: Pipeline run identifier.
        job_statuses: Mapping of job ID to terminal status.
        completed_job_ids: Frozenset of successfully completed jobs.
        snapshot_at: Timestamp when DAG snapshot was captured.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    completed_job_ids: frozenset[str] = Field(
        default_factory=frozenset,
        description="Set of successfully completed job IDs",
    )
    job_statuses: dict[str, JobStatus] = Field(
        default_factory=dict, description="Captured job statuses"
    )
    run_id: str = Field(description="Pipeline run identifier")
    snapshot_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Snapshot timestamp in UTC",
    )


class DagRewindRequest(BaseModel):
    """Request payload to rewind a failed or partially executed DAG run.

    Args:
        target_job_ids: List of job IDs to reset and restart along with downstream dependents.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    target_job_ids: list[str] = Field(
        default_factory=list,
        description="Seed job IDs to reset and re-execute. If empty, all failed tasks (or all tasks) are rewound.",
    )


class DagRewindReport(BaseModel):
    """Report summarizing the outcome of a DAG rewind operation.

    Args:
        run_id: Pipeline run identifier.
        rewound_job_ids: All job IDs reset to PENDING (targets + downstream dependents).
        re_enqueued_job_ids: Jobs immediately re-enqueued because prerequisites are satisfied.
        unaffected_job_ids: Jobs whose completed results are preserved.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    re_enqueued_job_ids: list[str] = Field(
        default_factory=list, description="Jobs immediately placed back on task queue"
    )
    rewound_job_ids: list[str] = Field(
        default_factory=list, description="Jobs reset to PENDING state"
    )
    run_id: str = Field(description="Pipeline run identifier")
    unaffected_job_ids: list[str] = Field(
        default_factory=list, description="Jobs whose prior results were reused"
    )
