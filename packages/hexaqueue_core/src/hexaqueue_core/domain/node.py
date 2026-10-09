"""Compute node health, provisioning tier, and cache affinity domain models.

Notes/Architectural Intent:
    Represents compute worker profiles, their operational health states,
    provisioning tier (static warm vs ephemeral burst), and Content-Addressable
    Storage (CAS) warm cache contents for zero-copy job dispatching.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.ports.resources import NodeCapacity


class NodeHealthState(StrEnum):
    """Operational health state of a compute worker node.

    Progression:
        HEALTHY -> UNHEALTHY (missed heartbeats) -> DEAD (timeout) -> DRAINED
        UNHEALTHY -> HEALTHY (pulse recovered)
    """

    HEALTHY = "HEALTHY"
    UNHEALTHY = "UNHEALTHY"
    DEAD = "DEAD"
    DRAINED = "DRAINED"


class NodeProvisioningTier(StrEnum):
    """Provisioning tier and lifecycle classification of a compute worker node.

    Tiers:
        STATIC: Permanent or pre-warmed bare-metal/VM instances with persistent local disk caches.
        EPHEMERAL: Dynamic on-demand cloud bursting nodes (provisioned via Crossplane or Cloud APIs)
                   that drain and terminate when idle.
    """

    STATIC = "STATIC"
    EPHEMERAL = "EPHEMERAL"


class ComputeNodeProfile(BaseModel):
    """Profile of an active or standby compute worker node.

    Args:
        node_id: Unique worker node identifier.
        tier: Node provisioning tier (STATIC vs EPHEMERAL).
        health_state: Operational health lifecycle state.
        cached_collateral_hashes: Set of CAS SHA-256 bundle hashes cached locally on disk.
        capacity: Hardware resource capacity and free slot descriptors.
        active_job_ids: Set of currently executing job identifiers on this node.
        last_heartbeat_at: Timestamp in UTC of the most recently received heartbeat pulse.
        registered_at: Timestamp in UTC when the worker registered with the controller.
        updated_at: Timestamp in UTC of the most recent profile state change.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_job_ids: frozenset[str] = Field(
        default_factory=frozenset, description="Active job identifiers on this node"
    )
    cached_collateral_hashes: frozenset[str] = Field(
        default_factory=frozenset,
        description="CAS SHA-256 hashes present in local disk cache",
    )
    capacity: NodeCapacity | None = Field(
        default=None, description="Discovered hardware capacity"
    )
    health_state: NodeHealthState = Field(
        default=NodeHealthState.HEALTHY, description="Current operational health"
    )
    last_heartbeat_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Most recent heartbeat timestamp in UTC",
    )
    node_id: str = Field(description="Unique node identifier")
    registered_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Registration timestamp in UTC",
    )
    tier: NodeProvisioningTier = Field(
        default=NodeProvisioningTier.STATIC, description="Provisioning tier"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last update timestamp in UTC",
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate required identifier fields.

        Returns:
            The validated ComputeNodeProfile instance.

        Raises:
            ValueError: If node_id is blank.
        """
        if not self.node_id.strip():
            msg = "node_id cannot be empty"
            raise ValueError(msg)
        return self

    @property
    def is_available(self) -> bool:
        """Check if node is currently eligible for new workload dispatch."""
        return self.health_state == NodeHealthState.HEALTHY

    def has_cached_collateral(self, sha256_checksum: str) -> bool:
        """Check if a specific collateral bundle hash is present in local cache.

        Args:
            sha256_checksum: SHA-256 digest of the desired collateral bundle.

        Returns:
            True if cached locally on this node, False otherwise.
        """
        return sha256_checksum in self.cached_collateral_hashes

    def touch_heartbeat(self) -> Self:
        """Record received heartbeat pulse and restore HEALTHY state if degraded.

        Returns:
            Updated ComputeNodeProfile instance.
        """
        now = datetime.now(UTC)
        target_state = (
            NodeHealthState.HEALTHY
            if self.health_state in (NodeHealthState.HEALTHY, NodeHealthState.UNHEALTHY)
            else self.health_state
        )
        return self.model_copy(
            update={
                "health_state": target_state,
                "last_heartbeat_at": now,
                "updated_at": now,
            }
        )

    def mark_unhealthy(self) -> Self:
        """Transition node to UNHEALTHY upon missed heartbeat pulses.

        Returns:
            Updated ComputeNodeProfile instance.
        """
        now = datetime.now(UTC)
        return self.model_copy(
            update={
                "health_state": NodeHealthState.UNHEALTHY,
                "updated_at": now,
            }
        )

    def mark_dead(self) -> Self:
        """Transition node to DEAD upon exceeding heartbeat failure threshold.

        Returns:
            Updated ComputeNodeProfile instance.
        """
        now = datetime.now(UTC)
        return self.model_copy(
            update={
                "health_state": NodeHealthState.DEAD,
                "updated_at": now,
            }
        )

    def mark_drained(self) -> Self:
        """Transition node to DRAINED after eviction of in-flight workloads.

        Returns:
            Updated ComputeNodeProfile instance.
        """
        now = datetime.now(UTC)
        return self.model_copy(
            update={
                "active_job_ids": frozenset(),
                "health_state": NodeHealthState.DRAINED,
                "updated_at": now,
            }
        )

    def add_cached_hash(self, sha256_checksum: str) -> Self:
        """Index a newly acquired collateral hash into the node's warm cache set.

        Args:
            sha256_checksum: SHA-256 hex digest of the fetched collateral bundle.

        Returns:
            Updated ComputeNodeProfile instance.
        """
        now = datetime.now(UTC)
        return self.model_copy(
            update={
                "cached_collateral_hashes": self.cached_collateral_hashes
                | {sha256_checksum},
                "updated_at": now,
            }
        )

    def assign_job(self, job_id: str) -> Self:
        """Track dispatch of an active job onto this node.

        Args:
            job_id: Identifier of the dispatched job.

        Returns:
            Updated ComputeNodeProfile instance.
        """
        now = datetime.now(UTC)
        return self.model_copy(
            update={
                "active_job_ids": self.active_job_ids | {job_id},
                "updated_at": now,
            }
        )

    def release_job(self, job_id: str) -> Self:
        """Release a finished or evicted job from the node's active set.

        Args:
            job_id: Identifier of the finished or evicted job.

        Returns:
            Updated ComputeNodeProfile instance.
        """
        now = datetime.now(UTC)
        return self.model_copy(
            update={
                "active_job_ids": self.active_job_ids - {job_id},
                "updated_at": now,
            }
        )


__all__ = [
    "ComputeNodeProfile",
    "NodeHealthState",
    "NodeProvisioningTier",
]
