"""Job retry policy and dead-letter queue (DLQ) domain entities.

Notes/Architectural Intent:
    Defines configurable retry policies (exponential backoff, retry caps)
    and dead-letter diagnostic records for failed tasks whose retry quotas
    have been exhausted.
"""

from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class JobRetryPolicy(BaseModel):
    """Configuration for automatic job recovery and exponential backoff retry.

    Args:
        max_retries: Maximum number of retry attempts before routing to the DLQ.
        backoff_factor: Multiplier applied to the backoff delay on each subsequent retry.
        initial_backoff_seconds: Initial delay in seconds before the first retry attempt.
        max_backoff_seconds: Maximum ceiling for computed backoff delay in seconds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    backoff_factor: float = Field(
        default=2.0, ge=1.0, description="Exponential backoff multiplier"
    )
    initial_backoff_seconds: float = Field(
        default=1.0, ge=0.0, description="Initial delay in seconds"
    )
    max_backoff_seconds: float = Field(
        default=60.0, ge=0.0, description="Maximum ceiling for retry delay"
    )
    max_retries: int = Field(
        default=3, ge=0, description="Maximum allowed retry attempts"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate backoff bounds.

        Returns:
            The validated JobRetryPolicy instance.

        Raises:
            ValueError: If initial_backoff_seconds exceeds max_backoff_seconds.
        """
        if self.initial_backoff_seconds > self.max_backoff_seconds:
            msg = (
                f"initial_backoff_seconds ({self.initial_backoff_seconds}) "
                f"cannot exceed max_backoff_seconds ({self.max_backoff_seconds})"
            )
            raise ValueError(msg)
        return self

    def compute_backoff_seconds(self, retry_count: int) -> float:
        """Calculate the exponential backoff delay for a given retry attempt.

        Args:
            retry_count: 1-indexed attempt number (1 for the first retry).

        Returns:
            Computed delay in seconds bounded by max_backoff_seconds.

        Notes/Architectural Intent:
            Uses deterministic exponential backoff:
            delay = min(initial * (factor ** (retry_count - 1)), max_backoff).
        """
        if retry_count <= 0:
            return 0.0
        exponent = max(0, retry_count - 1)
        calculated = self.initial_backoff_seconds * (self.backoff_factor**exponent)
        return min(calculated, self.max_backoff_seconds)


class DeadLetterRecord(BaseModel):
    """Diagnostic audit record preserved in the Dead-Letter Queue (DLQ).

    Args:
        job_id: Identifier of the failed job.
        run_id: Identifier of the parent pipeline run.
        failure_reason: Root-cause diagnostic explanation or unhandled exception.
        retry_count: Total retry attempts executed prior to DLQ routing.
        last_worker_id: Identifier of the last worker node that executed the job.
        diagnostics: Additional contextual key-value diagnostic tags.
        timestamp: Timestamp in UTC when the job was routed to the DLQ.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    diagnostics: dict[str, str] = Field(
        default_factory=dict, description="Diagnostic tags and environment details"
    )
    failure_reason: str = Field(description="Root-cause diagnostic explanation")
    job_id: str = Field(description="Identifier of the dead-lettered job")
    last_worker_id: str | None = Field(
        default=None, description="Identifier of the executing worker"
    )
    retry_count: int = Field(ge=0, description="Total attempts before exhaustion")
    run_id: str = Field(description="Root run identifier")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Routing timestamp in UTC",
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate required identifier fields.

        Returns:
            The validated DeadLetterRecord instance.

        Raises:
            ValueError: If job_id, run_id, or failure_reason is blank.
        """
        if not self.job_id.strip():
            msg = "job_id cannot be empty"
            raise ValueError(msg)
        if not self.run_id.strip():
            msg = "run_id cannot be empty"
            raise ValueError(msg)
        if not self.failure_reason.strip():
            msg = "failure_reason cannot be empty"
            raise ValueError(msg)
        return self


__all__ = [
    "DeadLetterRecord",
    "JobRetryPolicy",
]
