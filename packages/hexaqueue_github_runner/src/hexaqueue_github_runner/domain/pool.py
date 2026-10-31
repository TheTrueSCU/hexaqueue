"""Domain models for pre-warmed static and ephemeral runner pools.

Notes/Architectural Intent:
    Allows operators to configure pre-warmed pools of runners for micro-latency
    CI execution (0s queue wait) while enforcing fair-share limits.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RunnerPoolState(StrEnum):
    """Lifecycle states of runners managed in a warm pool."""

    IDLE = "idle"
    BUSY = "busy"
    DRAINING = "draining"
    TERMINATED = "terminated"


class WarmPoolRunner(BaseModel):
    """Individual runner member inside a warm runner pool.

    Args:
        runner_id: Numeric GitHub runner ID.
        runner_name: Human-readable unique runner name.
        pool_id: ID of owning warm pool.
        state: Current operational state.
        created_at: Creation timestamp in UTC.
        last_assigned_job_id: ID of the currently running or last executed job.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Creation timestamp UTC"
    )
    last_assigned_job_id: str | None = Field(default=None, description="Active job ID")
    pool_id: str = Field(description="Parent warm pool ID")
    runner_id: int = Field(description="Unique GitHub runner numeric ID")
    runner_name: str = Field(description="Runner name")
    state: RunnerPoolState = Field(
        default=RunnerPoolState.IDLE, description="Current pool status"
    )


class WarmPoolConfig(BaseModel):
    """Configuration for a pre-warmed runner pool.

    Args:
        pool_id: Unique identifier for the pool (e.g. 'gpu-ci-fast').
        labels: Runner labels registered with members of this pool.
        min_idle: Minimum number of warm idle runners to maintain.
        max_capacity: Hard ceiling on runners in this pool.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    labels: list[str] = Field(description="Runner label set")
    max_capacity: int = Field(default=10, ge=1, description="Max runner capacity")
    min_idle: int = Field(default=1, ge=0, description="Minimum idle runners")
    pool_id: str = Field(description="Warm pool identifier")


__all__ = [
    "RunnerPoolState",
    "WarmPoolConfig",
    "WarmPoolRunner",
]
