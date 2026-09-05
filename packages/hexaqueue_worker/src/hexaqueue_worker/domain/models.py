"""Domain models for worker configuration and metrics.

Notes/Architectural Intent:
    Defines configuration structures and status metrics for worker daemon operations,
    specifying concurrency thresholds, polling intervals, and scratch volume base paths.
"""

from pydantic import BaseModel, ConfigDict, Field


class WorkerConfig(BaseModel):
    """Configuration options for a compute worker daemon instance.

    Args:
        worker_id: Unique worker identifier.
        concurrency: Maximum number of concurrent jobs to execute.
        poll_interval_seconds: Polling interval when waiting for queued jobs.
        scratch_base_dir: Optional base directory for isolating scratch workspaces.
        grace_period_seconds: Timeout to wait after SIGTERM before SIGKILL.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    concurrency: int = Field(
        default=4, ge=1, description="Maximum concurrent job execution limit"
    )
    grace_period_seconds: int = Field(
        default=15, ge=1, description="Grace period before SIGKILL"
    )
    poll_interval_seconds: float = Field(
        default=0.1, gt=0.0, description="Queue polling interval in seconds"
    )
    scratch_base_dir: str | None = Field(
        default=None, description="Base directory for scratch storage allocations"
    )
    worker_id: str = Field(
        default="local-worker", description="Unique worker instance identifier"
    )


class WorkerMetrics(BaseModel):
    """Real-time operational metrics of a compute worker.

    Args:
        worker_id: Unique worker identifier.
        active_jobs: Count of jobs currently executing.
        total_executed: Total count of jobs executed since startup.
        total_failed: Total count of failed jobs.
        total_completed: Total count of successfully completed jobs.
        is_running: Whether the worker execution loop is active.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_jobs: int = Field(ge=0, description="Number of currently executing jobs")
    is_running: bool = Field(description="Whether the worker daemon is running")
    total_completed: int = Field(
        default=0, ge=0, description="Total completed jobs count"
    )
    total_executed: int = Field(
        default=0, ge=0, description="Total executed jobs count"
    )
    total_failed: int = Field(default=0, ge=0, description="Total failed jobs count")
    worker_id: str = Field(description="Worker instance identifier")


__all__ = [
    "WorkerConfig",
    "WorkerMetrics",
]
