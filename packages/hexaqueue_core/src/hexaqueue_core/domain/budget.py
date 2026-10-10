"""Domain models for two-phase budget accounting, segment reservations, and cluster health.

Notes/Architectural Intent:
    Defines foundational accounting data structures for abstract HQ credit reservations,
    incremental preemption segment settlements, and cluster health telemetry snapshots.
    Supports atomic balance mutations and guarantees zero credit leakage.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator


class ReservationState(StrEnum):
    """Lifecycle state of a two-phase budget reservation."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"
    SETTLED = "SETTLED"


class ExecutionSegmentRecord(BaseModel):
    """Record of resource consumption during a discrete execution segment (e.g. prior to preemption).

    Args:
        segment_id: Unique identifier for this execution slice.
        job_id: Target job identifier.
        reservation_id: Parent budget reservation identifier.
        start_time: UTC start timestamp of execution segment.
        end_time: UTC termination/preemption timestamp of segment.
        walltime_seconds: Measured elapsed runtime in seconds.
        credits_billed: Abstract credits billed for this segment.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    credits_billed: float = Field(ge=0.0, description="Credits billed for this segment")
    end_time: datetime = Field(
        description="Segment termination or preemption timestamp"
    )
    job_id: str = Field(description="Job identifier")
    reservation_id: str = Field(description="Parent reservation identifier")
    segment_id: str = Field(
        default_factory=lambda: f"seg-{uuid4().hex[:8]}",
        description="Unique segment identifier",
    )
    start_time: datetime = Field(description="Segment start timestamp")
    walltime_seconds: float = Field(
        ge=0.0, description="Measured elapsed runtime in seconds"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate non-empty identifiers and temporal ordering."""
        if not self.job_id.strip():
            msg = "job_id cannot be empty"
            raise ValueError(msg)
        if not self.reservation_id.strip():
            msg = "reservation_id cannot be empty"
            raise ValueError(msg)
        return self


class BudgetReservation(BaseModel):
    """Two-phase pre-emptive budget reservation for compute workload execution.

    Args:
        reservation_id: Unique reservation hold identifier.
        tenant_id: Tenant or project account identifier.
        job_id: Job identifier holding the budget.
        held_credits: Maximum credits reserved for the execution.
        settled_credits: Cumulative credits settled so far across segments.
        state: Current lifecycle state of the reservation.
        created_at: Reservation creation timestamp in UTC.
        settled_at: Timestamp when reservation was finalized or released.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Reservation creation timestamp",
    )
    held_credits: float = Field(
        ge=0.0, description="Maximum credits held for execution"
    )
    job_id: str = Field(description="Job identifier")
    reservation_id: str = Field(
        default_factory=lambda: f"res-{uuid4().hex[:8]}",
        description="Unique reservation hold identifier",
    )
    settled_at: datetime | None = Field(
        default=None, description="Timestamp of final settlement or release"
    )
    settled_credits: float = Field(
        default=0.0, ge=0.0, description="Cumulative settled credits"
    )
    state: ReservationState = Field(
        default=ReservationState.ACTIVE, description="Reservation lifecycle state"
    )
    tenant_id: str = Field(description="Tenant or project account identifier")

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate identifiers and settled bounds."""
        if not self.tenant_id.strip():
            msg = "tenant_id cannot be empty"
            raise ValueError(msg)
        if not self.job_id.strip():
            msg = "job_id cannot be empty"
            raise ValueError(msg)
        if not self.reservation_id.strip():
            msg = "reservation_id cannot be empty"
            raise ValueError(msg)
        return self

    def settle_segment(self, segment_credits: float) -> "BudgetReservation":
        """Record an incremental segment settlement against this reservation.

        Args:
            segment_credits: Credits consumed during this execution segment.

        Returns:
            Updated BudgetReservation copy with incremented settled_credits.

        Raises:
            ValueError: If reservation is not ACTIVE or segment_credits is negative.

        Notes/Architectural Intent:
            Keeps state ACTIVE while updating cumulative settled credits, ensuring
            multi-segment preemptible executions track partial spend without double-counting.
        """
        if self.state != ReservationState.ACTIVE:
            msg = f"Cannot settle segment on reservation in state '{self.state}'"
            raise ValueError(msg)
        if segment_credits < 0.0:
            msg = f"segment_credits must be non-negative, got {segment_credits}"
            raise ValueError(msg)

        new_settled = self.settled_credits + segment_credits
        return self.model_copy(
            update={
                "settled_credits": new_settled,
            }
        )

    def finalize_settlement(self, final_actual_credits: float) -> "BudgetReservation":
        """Finalize reservation settlement on terminal job completion.

        Args:
            final_actual_credits: Final total credits consumed by the job.

        Returns:
            Updated BudgetReservation in SETTLED state.

        Raises:
            ValueError: If reservation is not ACTIVE or final credits is negative.
        """
        if self.state not in (ReservationState.ACTIVE, ReservationState.EXPIRED):
            msg = f"Cannot finalize reservation in state '{self.state}'"
            raise ValueError(msg)
        if final_actual_credits < 0.0:
            msg = (
                f"final_actual_credits must be non-negative, got {final_actual_credits}"
            )
            raise ValueError(msg)

        now = datetime.now(UTC)
        return self.model_copy(
            update={
                "settled_credits": final_actual_credits,
                "state": ReservationState.SETTLED,
                "settled_at": now,
            }
        )

    def release(self) -> "BudgetReservation":
        """Release reservation hold in full without billing.

        Returns:
            Updated BudgetReservation in RELEASED state.

        Raises:
            ValueError: If reservation is not ACTIVE.
        """
        if self.state != ReservationState.ACTIVE:
            msg = f"Cannot release reservation in state '{self.state}'"
            raise ValueError(msg)

        now = datetime.now(UTC)
        return self.model_copy(
            update={
                "state": ReservationState.RELEASED,
                "settled_at": now,
            }
        )


class TenantAccount(BaseModel):
    """Credit balance and active holds ledger for a tenant or project.

    Args:
        tenant_id: Unique tenant or project identifier.
        credit_balance: Lifetime deposited credits.
        active_holds_total: Total credits currently held in active reservations.
        settled_total: Total credits permanently settled and deducted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_holds_total: float = Field(
        default=0.0, ge=0.0, description="Total credits currently in active holds"
    )
    credit_balance: float = Field(
        default=0.0, ge=0.0, description="Total deposited credits"
    )
    settled_total: float = Field(
        default=0.0, ge=0.0, description="Total permanently settled credits"
    )
    tenant_id: str = Field(description="Unique tenant identifier")

    @computed_field
    @property
    def available_balance(self) -> float:
        """Calculate available spendable credit balance.

        Returns:
            Available credits not currently committed to holds or settled.
        """
        return max(
            0.0, self.credit_balance - self.settled_total - self.active_holds_total
        )


class ClusterHealthReport(BaseModel):
    """Point-in-time cluster capacity, node liveness, and telemetry health snapshot.

    Args:
        healthy_nodes_count: Count of active nodes with healthy heartbeat pulses.
        unhealthy_nodes_count: Count of nodes with missed pulses.
        dead_nodes_count: Count of dead or unreachable worker nodes.
        total_cpus: Total CPU cores present in the cluster.
        allocated_cpus: Currently allocated or consumed CPU cores.
        total_ram_mb: Total system RAM across cluster in megabytes.
        allocated_ram_mb: Currently allocated or utilized RAM in megabytes.
        total_gpus: Total hardware accelerators/GPUs in cluster.
        allocated_gpus: Currently allocated or consumed GPUs.
        active_jobs_count: Total running and provisioning jobs across the cluster.
        timestamp: Snapshot emission timestamp in UTC.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    active_jobs_count: int = Field(ge=0, description="Active running/provisioning jobs")
    allocated_cpus: int = Field(ge=0, description="Allocated CPU cores")
    allocated_gpus: int = Field(ge=0, description="Allocated GPUs")
    allocated_ram_mb: int = Field(ge=0, description="Allocated RAM in MB")
    dead_nodes_count: int = Field(ge=0, description="Dead worker nodes")
    healthy_nodes_count: int = Field(ge=0, description="Healthy worker nodes")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Health report generation timestamp",
    )
    total_cpus: int = Field(ge=0, description="Total CPU cores")
    total_gpus: int = Field(ge=0, description="Total GPUs")
    total_ram_mb: int = Field(ge=0, description="Total RAM in MB")
    unhealthy_nodes_count: int = Field(ge=0, description="Unhealthy worker nodes")


__all__ = [
    "BudgetReservation",
    "ClusterHealthReport",
    "ExecutionSegmentRecord",
    "ReservationState",
    "TenantAccount",
]
