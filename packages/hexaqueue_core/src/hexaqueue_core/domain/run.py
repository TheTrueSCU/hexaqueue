"""Hierarchical Run and Workload Tree domain definitions.

Notes/Architectural Intent:
    Represents the top-level execution unit containing a collection of leaf jobs.
    Calculates aggregated RunState and terminal RunOutcome as pure projections.
"""

from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import (
    RunOutcome,
    RunState,
    compute_run_outcome,
    compute_run_state,
)


class RunSpec(BaseModel):
    """Specification of an aggregated workload run.

    Args:
        id: Globally unique run identifier (e.g. 'run_10928').
        name: Human-readable run name.
        jobs: List of constituent concrete leaf jobs.
        tags: Metadata tags.
        created_at: Creation timestamp in UTC.
        updated_at: Last update timestamp in UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Unique run identifier")
    name: str = Field(description="Run name")
    jobs: list[JobSpec] = Field(default_factory=list, description="Constituent jobs")
    tags: list[str] = Field(default_factory=list, description="Metadata tags")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def state(self) -> RunState:
        """Dynamically compute the aggregated RunState from constituent leaf jobs."""
        job_states = [job.state for job in self.jobs]
        return compute_run_state(job_states)

    @property
    def outcome(self) -> RunOutcome | None:
        """Compute the aggregated RunOutcome if the run is in DONE state."""
        if self.state != RunState.DONE:
            return None
        outcomes = [job.outcome for job in self.jobs if job.outcome is not None]
        return compute_run_outcome(outcomes)

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate run invariants."""
        if not self.id.strip():
            msg = "Run id cannot be empty"
            raise ValueError(msg)
        return self
