"""Unit tests for budget domain models, reservations, segments, and cluster health reports.

Notes/Architectural Intent:
    Verifies state transitions, invariant validation, segment accumulation,
    and available balance calculations for budget entities.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from hexaqueue_core.domain.budget import (
    BudgetReservation,
    ClusterHealthReport,
    ExecutionSegmentRecord,
    ReservationState,
    TenantAccount,
)


def test_budget_reservation_lifecycle() -> None:
    """Verify budget reservation segment settlement, finalization, and release transitions."""
    res = BudgetReservation(
        tenant_id="tenant-acct-1",
        job_id="job-123",
        held_credits=100.0,
    )
    assert res.state == ReservationState.ACTIVE
    assert res.settled_credits == 0.0

    # Incremental segment settlement
    res_seg = res.settle_segment(20.0)
    assert res_seg.state == ReservationState.ACTIVE
    assert res_seg.settled_credits == 20.0

    # Negative segment settlement rejected
    with pytest.raises(ValueError, match="non-negative"):
        res_seg.settle_segment(-5.0)

    # Finalize settlement
    res_final = res_seg.finalize_settlement(25.0)
    assert res_final.state == ReservationState.SETTLED
    assert res_final.settled_credits == 25.0
    assert res_final.settled_at is not None

    # Cannot settle or release finalized reservation
    with pytest.raises(ValueError, match="inactive|Cannot"):
        res_final.settle_segment(5.0)
    with pytest.raises(ValueError, match="Cannot finalize"):
        res_final.finalize_settlement(30.0)
    with pytest.raises(ValueError, match="Cannot release"):
        res_final.release()


def test_budget_reservation_release() -> None:
    """Verify immediate release of an active budget reservation."""
    res = BudgetReservation(
        tenant_id="tenant-acct-2",
        job_id="job-456",
        held_credits=50.0,
    )
    released = res.release()
    assert released.state == ReservationState.RELEASED
    assert released.settled_at is not None


def test_execution_segment_record() -> None:
    """Verify ExecutionSegmentRecord creation and validation."""
    now = datetime.now(UTC)
    seg = ExecutionSegmentRecord(
        job_id="job-preempt",
        reservation_id="res-hold-1",
        start_time=now,
        end_time=now,
        walltime_seconds=60.0,
        credits_billed=1.5,
    )
    assert seg.job_id == "job-preempt"
    assert seg.walltime_seconds == 60.0

    # Empty identifiers rejected
    with pytest.raises(ValidationError):
        ExecutionSegmentRecord(
            job_id="",
            reservation_id="res-1",
            start_time=now,
            end_time=now,
            walltime_seconds=10.0,
            credits_billed=1.0,
        )


def test_tenant_account_available_balance() -> None:
    """Verify TenantAccount available balance calculation."""
    acct = TenantAccount(
        tenant_id="tenant-xyz",
        credit_balance=500.0,
        active_holds_total=100.0,
        settled_total=150.0,
    )
    # Available = 500 - 150 - 100 = 250
    assert acct.available_balance == 250.0

    # Overdrawn case floors at 0.0
    acct_overdrawn = TenantAccount(
        tenant_id="tenant-xyz",
        credit_balance=100.0,
        active_holds_total=80.0,
        settled_total=50.0,
    )
    assert acct_overdrawn.available_balance == 0.0


def test_budget_reservation_finalize_expired() -> None:
    """Verify an EXPIRED reservation can still be finalized upon job completion."""
    res = BudgetReservation(
        tenant_id="tenant-exp",
        job_id="job-exp",
        held_credits=50.0,
        state=ReservationState.EXPIRED,
    )
    finalized = res.finalize_settlement(45.0)
    final_state = finalized.state
    final_credits = finalized.settled_credits
    assert final_state == ReservationState.SETTLED
    assert final_credits == 45.0


def test_cluster_health_report() -> None:
    """Verify ClusterHealthReport instantiates with non-negative metrics."""
    report = ClusterHealthReport(
        healthy_nodes_count=5,
        unhealthy_nodes_count=1,
        dead_nodes_count=0,
        total_cpus=64,
        allocated_cpus=32,
        total_ram_mb=131072,
        allocated_ram_mb=65536,
        total_gpus=8,
        allocated_gpus=4,
        active_jobs_count=12,
    )
    healthy_val = report.healthy_nodes_count
    cpus_val = report.total_cpus
    gpus_val = report.allocated_gpus
    assert healthy_val == 5
    assert cpus_val == 64
    assert gpus_val == 4


__all__ = [
    "test_budget_reservation_finalize_expired",
    "test_budget_reservation_lifecycle",
    "test_budget_reservation_release",
    "test_cluster_health_report",
    "test_execution_segment_record",
    "test_tenant_account_available_balance",
]
