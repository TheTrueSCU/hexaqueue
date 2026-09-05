"""Job and Task domain entity definitions.

Notes/Architectural Intent:
    Represents concrete leaf executable tasks with their resource requirements,
    command line arguments, environment variables, collateral attachments, and
    lifecycle status tracking.
"""

from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.lifecycle import JobState, JobStatus, TerminalOutcome
from hexaqueue_core.domain.resources import ResourceRequirements


class JobSpec(BaseModel):
    """Specification of a concrete leaf job to be dispatched and executed.

    Args:
        id: Globally unique job identifier (e.g. 'job_482910').
        run_id: Root parent run identifier.
        name: Human-readable job name or test identifier.
        command: Executable command string or entrypoint.
        args: List of command-line arguments.
        env: Dictionary of environment variables.
        resources: Compute and hardware requirements.
        collateral_ids: Associated collateral bundle IDs required by this job.
        tags: Categorization tags for node affinity and filtering.
        status: Current lifecycle state and history.
        created_at: Creation timestamp in UTC.
        updated_at: Last update timestamp in UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Unique job identifier")
    run_id: str = Field(description="Associated root run ID")
    name: str = Field(description="Job name")
    command: str = Field(description="Executable command")
    args: list[str] = Field(default_factory=list, description="Command arguments")
    env: dict[str, str] = Field(
        default_factory=dict, description="Environment variables"
    )
    resources: ResourceRequirements = Field(
        default_factory=ResourceRequirements, description="Resource requirements"
    )
    collateral_ids: list[str] = Field(
        default_factory=list, description="Required collateral bundle IDs"
    )
    tags: list[str] = Field(
        default_factory=list, description="Affinity & placement tags"
    )
    status: JobStatus = Field(default_factory=JobStatus, description="Lifecycle status")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def state(self) -> JobState:
        """Convenience property for current job state."""
        return self.status.state

    @property
    def outcome(self) -> TerminalOutcome | None:
        """Convenience property for terminal outcome."""
        return self.status.outcome

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate job invariants."""
        if not self.id.strip():
            msg = "Job id cannot be empty"
            raise ValueError(msg)
        if not self.command.strip():
            msg = "Job command cannot be empty"
            raise ValueError(msg)
        return self
