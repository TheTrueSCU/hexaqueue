"""Domain models for central scheduler controller operations.

Notes/Architectural Intent:
    Defines foundational run submission payloads, status reports, and
    protocol-neutral task queue contracts compatible with Hexastack and Hexaqual runners.
"""

from datetime import UTC, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.freetier import FreeTierBurnReport
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import RunOutcome, RunState
from hexaqueue_core.domain.run import RunSpec


class RunSubmission(BaseModel):
    """Submission payload to trigger a multi-job DAG run pipeline.

    Args:
        run_spec: Root run metadata specification.
        jobs: List of JobSpecs belonging to this pipeline.
        dependencies: Adjacency dictionary mapping child_job_id -> list of prerequisite parent_job_ids.

    Notes/Architectural Intent:
        Represents validated input for multi-stage execution pipelines, enforcing
        prerequisite reference symmetry before scheduling.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    dependencies: dict[str, list[str]] = Field(
        default_factory=dict, description="Job dependency adjacency mapping"
    )
    jobs: list[JobSpec] = Field(min_length=1, description="List of jobs in this run")
    run_spec: RunSpec = Field(description="Pipeline run specification")

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate submission invariants."""
        job_ids = {j.id for j in self.jobs}
        for child_id, parents in self.dependencies.items():
            if child_id not in job_ids:
                msg = f"Dependency child job '{child_id}' not found in jobs list"
                raise ValueError(msg)
            for parent_id in parents:
                if parent_id not in job_ids:
                    msg = f"Dependency parent job '{parent_id}' not found in jobs list"
                    raise ValueError(msg)
        return self


class RunStatusReport(BaseModel):
    """Comprehensive snapshot of a pipeline run's execution status.

    Args:
        run_id: Root run identifier.
        state: Aggregated RunState (PENDING, RUNNING, DONE).
        outcome: Terminal RunOutcome (COMPLETED, FAILED, TIMED_OUT, CANCELLED) if DONE.
        total_jobs: Total jobs count in pipeline.
        completed_jobs: Number of completed jobs.
        failed_jobs: Number of failed jobs.
        running_jobs: Number of currently executing jobs.
        pending_jobs: Number of pending/blocked jobs.
        created_at: Run creation timestamp.
        updated_at: Status report generation timestamp.
        id: Optional alias for run_id for generic consumer protocol parity.
        status: Optional generic consumer status projection.
        completed_steps: List of completed step names.
        failed_steps: List of failed step names.
        outputs: Step outputs map.
        burn_report: Optional free-tier burn report.
        free_tier_active: Flag indicating free-tier constraints.

    Notes/Architectural Intent:
        Exposes unified status projection satisfying both native Hexaqueue consumers
        and Hexastack HexaqueueWorkflowOrchestratorAdapter consumers.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    burn_report: FreeTierBurnReport | None = Field(
        default=None, description="Current free-tier quota burn report"
    )
    completed_jobs: int = Field(ge=0, description="Completed jobs count")
    completed_steps: list[str] = Field(
        default_factory=list, description="List of completed steps or job IDs"
    )
    created_at: datetime = Field(description="Run creation timestamp")
    failed_jobs: int = Field(ge=0, description="Failed jobs count")
    failed_steps: list[str] = Field(
        default_factory=list, description="List of failed steps or job IDs"
    )
    free_tier_active: bool = Field(
        default=False,
        description="Whether cluster is operating under Free-Tier Safety Mode",
    )
    id: str | None = Field(
        default=None,
        description="Alias for run_id for generic consumer protocol parity",
    )
    outcome: RunOutcome | None = Field(
        default=None, description="Terminal outcome if DONE"
    )
    outputs: dict[str, Any] = Field(
        default_factory=dict, description="Step outputs map"
    )
    pending_jobs: int = Field(ge=0, description="Pending jobs count")
    run_id: str = Field(description="Run identifier")
    running_jobs: int = Field(ge=0, description="Running jobs count")
    state: RunState = Field(description="Aggregate run state")
    status: str | None = Field(
        default=None, description="Generic consumer status projection"
    )
    total_jobs: int = Field(ge=1, description="Total jobs count")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Update timestamp"
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_report_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            d = dict(data)
            run_id = d.get("run_id") or d.get("id")
            if run_id:
                d["run_id"] = str(run_id)
                d["id"] = str(run_id)
            if "status" not in d or d["status"] is None:
                outcome = d.get("outcome")
                state = d.get("state")
                d["status"] = str(
                    outcome.value
                    if hasattr(outcome, "value")
                    else (
                        outcome
                        or (state.value if hasattr(state, "value") else state)
                        or "RUNNING"
                    )
                )
            return d
        return data


class TaskQueueJobRequest(BaseModel):
    """Payload to enqueue a task into the distributed task queue.

    Args:
        task_name: Task handler/function name.
        payload: Input parameters.
        partition_key: Optional partition key for ordered worker routing.
        priority: Task priority.
        max_attempts: Maximum retry attempts before dead-lettering.
        queue: Target queue partition name.

    Notes/Architectural Intent:
        Matches Hexastack HexaqueueTaskQueueAdapter task submission contract.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    max_attempts: int = Field(default=3, description="Maximum retry attempts")
    partition_key: str | None = Field(
        default=None, description="Optional partition key for ordered worker routing"
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Task payload parameters"
    )
    priority: int = Field(default=0, description="Task execution priority")
    queue: str = Field(default="default", description="Target queue partition name")
    task_name: str = Field(description="Name or entrypoint of task to execute")


class TaskQueueLeaseRequest(BaseModel):
    """Payload to acquire a lease on next available tasks.

    Args:
        worker_id: Unique worker agent identifier.
        task_names: Optional filter for specific task names.
        lease_duration_seconds: Time before lease expires if not renewed.
        queue: Target queue partition name.

    Notes/Architectural Intent:
        Matches Hexastack HexaqueueTaskQueueAdapter task leasing contract.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    lease_duration_seconds: float = Field(
        default=30.0, description="Lease timeout duration in seconds"
    )
    queue: str = Field(default="default", description="Target queue partition name")
    task_names: list[str] | None = Field(
        default=None, description="Optional filter for specific task names"
    )
    worker_id: str = Field(description="Unique worker agent identifier")


class TaskQueueCompleteRequest(BaseModel):
    """Payload to mark a leased task as successfully completed.

    Args:
        worker_id: Optional worker identifier to verify lease ownership.

    Notes/Architectural Intent:
        Acknowledges task completion from worker nodes.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    worker_id: str | None = Field(default=None, description="Worker identifier")


class TaskQueueFailRequest(BaseModel):
    """Payload to mark a leased task as failed.

    Args:
        worker_id: Optional worker identifier.
        error: Failure error details.

    Notes/Architectural Intent:
        Records task failure and triggers retry or dead-letter handling.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    error: str | None = Field(default=None, description="Failure error details")
    worker_id: str | None = Field(default=None, description="Worker identifier")


class TaskRecordResponse(BaseModel):
    """Response model representing a leased or enqueued task record.

    Args:
        id: Task record identifier.
        task_name: Task handler name.
        payload: Input parameters.
        state: Current task state.
        partition_key: Optional partition key.
        priority: Priority value.
        attempts: Number of executed attempts.
        max_attempts: Maximum retry attempts.
        lease_owner: Current worker holding lease.
        lease_expires_at: Expiration timestamp.
        created_at: Creation timestamp.
        completed_at: Completion timestamp.
        last_error: Error message if failed.

    Notes/Architectural Intent:
        Serialized response conforming to Hexastack TaskRecord domain structure.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    attempts: int = Field(default=0, description="Attempt count")
    completed_at: float | None = Field(default=None, description="Completion timestamp")
    created_at: float = Field(
        default_factory=lambda: datetime.now(UTC).timestamp(),
        description="Creation timestamp",
    )
    id: str = Field(description="Unique task identifier")
    last_error: str | None = Field(default=None, description="Last recorded error")
    lease_expires_at: float | None = Field(
        default=None, description="Lease expiration timestamp"
    )
    lease_owner: str | None = Field(default=None, description="Worker ID holding lease")
    max_attempts: int = Field(default=3, description="Maximum retry attempts")
    partition_key: str | None = Field(
        default=None, description="Optional partition key"
    )
    payload: dict[str, Any] = Field(
        default_factory=dict, description="Task payload parameters"
    )
    priority: int = Field(default=0, description="Task execution priority")
    state: str = Field(default="PENDING", description="Task lifecycle state")
    task_name: str = Field(description="Task name")


__all__ = [
    "RunStatusReport",
    "RunSubmission",
    "TaskQueueCompleteRequest",
    "TaskQueueFailRequest",
    "TaskQueueJobRequest",
    "TaskQueueLeaseRequest",
    "TaskRecordResponse",
]
