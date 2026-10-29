"""Instance pool configuration, state, and autoscaling domain models.

Notes/Architectural Intent:
    Defines foundational abstractions for managing self-scaling compute instance
    pools across Cloud Service Providers (AWS ASG, GCP MIG, Azure VMSS).
    Maintains capacity bounds, capability tagging for hardware-aware scheduling,
    and autoscaler decisions with budget throttling guards.
"""

from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.config import CspProvider


class InstancePoolState(BaseModel):
    """Snapshot of an active or managed cloud compute instance pool.

    Args:
        pool_id: Unique pool identifier (e.g. ASG name, MIG URL, VMSS name).
        provider: Target Cloud Service Provider.
        min_nodes: Minimum pool scaling floor (e.g. 0 for scale-from-zero).
        max_nodes: Maximum pool scaling ceiling.
        desired_nodes: Desired node count configured on the CSP pool.
        current_nodes: Currently provisioned instance count.
        ready_nodes: Active nodes joined to cluster and ready for scheduling.
        spot_nodes: Number of active spot/preemptible instances.
        capability_tags: Capability tags supported by this pool (e.g. 'os:windows', 'gpu:a100').
        idle_drain_seconds: Inactivity cooldown in seconds before scaling to zero.
        updated_at: Timestamp in UTC of state snapshot.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_tags: frozenset[str] = Field(
        default_factory=frozenset,
        description="Capability tags matching job requirement selectors",
    )
    current_nodes: int = Field(
        default=0, ge=0, description="Currently launched instance count"
    )
    desired_nodes: int = Field(
        default=0, ge=0, description="Target capacity requested from CSP"
    )
    idle_drain_seconds: int = Field(
        default=300, ge=0, description="Idle cooldown before scale-to-zero"
    )
    max_nodes: int = Field(default=10, ge=0, description="Upper bound instance ceiling")
    min_nodes: int = Field(default=0, ge=0, description="Lower bound instance floor")
    pool_id: str = Field(description="Unique pool identifier")
    provider: CspProvider = Field(description="Associated CSP Provider")
    ready_nodes: int = Field(
        default=0, ge=0, description="Healthy nodes ready to accept tasks"
    )
    spot_nodes: int = Field(
        default=0, ge=0, description="Count of spot or preemptible instances"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Snapshot timestamp in UTC",
    )

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        """Validate non-empty pool_id and scaling boundary ordering.

        Returns:
            Validated instance.

        Raises:
            ValueError: If pool_id is empty or min_nodes exceeds max_nodes.
        """
        if not self.pool_id.strip():
            msg = "pool_id cannot be empty"
            raise ValueError(msg)
        if self.min_nodes > self.max_nodes:
            msg = f"min_nodes ({self.min_nodes}) cannot exceed max_nodes ({self.max_nodes})"
            raise ValueError(msg)
        return self


class PoolScaleRequest(BaseModel):
    """Request payload to resize an instance pool.

    Args:
        pool_id: Target instance pool identifier.
        target_nodes: Target node count requested.
        reason: Operational explanation for the scaling action.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pool_id: str = Field(description="Target instance pool identifier")
    reason: str = Field(default="Queue demand scaling", description="Scaling reason")
    target_nodes: int = Field(ge=0, description="Target node count")

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate non-empty pool_id.

        Returns:
            Validated instance.

        Raises:
            ValueError: If pool_id is empty.
        """
        if not self.pool_id.strip():
            msg = "pool_id cannot be empty"
            raise ValueError(msg)
        return self


class PoolScaleResult(BaseModel):
    """Result of an instance pool resize operation.

    Args:
        pool_id: Target instance pool identifier.
        previous_nodes: Node count prior to resize.
        target_nodes: New target node count applied to CSP.
        success: Whether the resizing call succeeded.
        message: Informational or error message from the CSP driver.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    message: str = Field(default="", description="Driver execution status message")
    pool_id: str = Field(description="Target instance pool identifier")
    previous_nodes: int = Field(ge=0, description="Node count prior to resize")
    success: bool = Field(description="Whether scaling succeeded")
    target_nodes: int = Field(ge=0, description="Target node count applied")


class AutoscalerDecision(BaseModel):
    """Decision output generated by the queue-depth and budget autoscaler.

    Args:
        pool_id: Target instance pool identifier.
        action: Decided action ('SCALE_UP', 'SCALE_DOWN', 'NOOP', 'THROTTLED_BUDGET').
        current_nodes: Currently provisioned nodes.
        target_nodes: Proposed target nodes.
        pending_jobs: Number of pending jobs matching pool capabilities.
        reason: Detailed justification for the autoscaler decision.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: str = Field(description="Autoscaler action taken")
    current_nodes: int = Field(ge=0, description="Current node count")
    pending_jobs: int = Field(ge=0, description="Matching pending job count")
    pool_id: str = Field(description="Target pool identifier")
    reason: str = Field(description="Reason for decision")
    target_nodes: int = Field(ge=0, description="Target node count")
