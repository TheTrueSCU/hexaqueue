"""Domain models for central scheduler controller operations."""

from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import RunOutcome, RunState
from hexaqueue_core.domain.run import RunSpec


class RunSubmission(BaseModel):
    """Submission payload to trigger a multi-job DAG run pipeline.

    Args:
        run_spec: Root run metadata specification.
        jobs: List of JobSpecs belonging to this pipeline.
        dependencies: Adjacency dictionary mapping child_job_id -> list of prerequisite parent_job_ids.
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
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    completed_jobs: int = Field(ge=0, description="Completed jobs count")
    created_at: datetime = Field(description="Run creation timestamp")
    failed_jobs: int = Field(ge=0, description="Failed jobs count")
    outcome: RunOutcome | None = Field(
        default=None, description="Terminal outcome if DONE"
    )
    pending_jobs: int = Field(ge=0, description="Pending jobs count")
    run_id: str = Field(description="Run identifier")
    running_jobs: int = Field(ge=0, description="Running jobs count")
    state: RunState = Field(description="Aggregate run state")
    total_jobs: int = Field(ge=1, description="Total jobs count")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Update timestamp"
    )


__all__ = [
    "RunStatusReport",
    "RunSubmission",
]
