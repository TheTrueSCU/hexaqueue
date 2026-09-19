"""Domain models for CLI cluster monitoring and statistics.

Notes/Architectural Intent:
    Defines presentation and reporting payloads for `hq stat`, `hq top`, and `hq nodes`.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


class ClusterStatsReport(BaseModel):
    """Aggregate cluster state, backlog, and worker capacity metrics.

    Args:
        total_runs: Count of active/historical runs.
        total_jobs: Total jobs registered in cluster.
        running_jobs: Jobs actively executing in compute worker slots.
        pending_jobs: Jobs queued and awaiting eligible compute slots.
        blocked_jobs: Jobs blocked on dependencies or administrative holds.
        completed_jobs: Jobs terminated successfully.
        failed_jobs: Jobs terminated with failure or error.
        active_workers: Count of active worker daemons.
        timestamp: Report generation timestamp.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_workers: int = Field(
        default=1, ge=0, description="Active worker daemons count"
    )
    blocked_jobs: int = Field(default=0, ge=0, description="Blocked jobs count")
    completed_jobs: int = Field(default=0, ge=0, description="Completed jobs count")
    failed_jobs: int = Field(default=0, ge=0, description="Failed jobs count")
    pending_jobs: int = Field(default=0, ge=0, description="Pending jobs count")
    running_jobs: int = Field(default=0, ge=0, description="Running jobs count")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Stats snapshot timestamp",
    )
    total_jobs: int = Field(default=0, ge=0, description="Total jobs count")
    total_runs: int = Field(default=0, ge=0, description="Total runs count")


__all__ = [
    "ClusterStatsReport",
]
