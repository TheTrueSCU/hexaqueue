"""Unit tests for budget accounting, reservations, and cluster health CQRS handlers."""

from typing import Any

from hexaqueue_core.domain.cqrs import (
    GetClusterHealthQuery,
    GetTenantBalanceQuery,
    ReleaseBudgetCommand,
    ReserveBudgetCommand,
    SettleBudgetCommand,
    SettleSegmentCommand,
)


def test_budget_reservation_and_settlement_cqrs(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify ReserveBudget, SettleSegment, and SettleBudget handlers."""
    _, pipeline = hermetic_cqrs_pipeline

    # 1. Reserve budget
    reserve_res = pipeline.execute(
        ReserveBudgetCommand(
            tenant_id="tenant-alpha",
            job_id="job-101",
            estimated_credits=100.0,
        )
    )
    res_id = reserve_res["reservation_id"]
    res_status = reserve_res["status"]
    assert res_status == "RESERVED"
    assert res_id.startswith("hold-")

    # 2. Check balance query
    account = pipeline.execute(GetTenantBalanceQuery(tenant_id="tenant-alpha"))
    bal = account.available_balance
    holds = account.active_holds_total
    assert bal == 9900.0
    assert holds == 100.0

    # 3. Settle segment (preemption)
    seg_res = pipeline.execute(
        SettleSegmentCommand(
            reservation_id=res_id,
            segment_credits=25.0,
        )
    )
    seg_status = seg_res["status"]
    cum_credits = seg_res["cumulative_credits"]
    assert seg_status == "SEGMENT_SETTLED"
    assert cum_credits == 25.0

    # 4. Final settlement without double-counting
    settle_res = pipeline.execute(
        SettleBudgetCommand(
            reservation_id=res_id,
            actual_credits=50.0,
        )
    )
    settle_status = settle_res["status"]
    act = settle_res["actual_credits"]
    assert settle_status == "SETTLED"
    assert act == 50.0

    # Verify final account balance
    updated_account = pipeline.execute(GetTenantBalanceQuery(tenant_id="tenant-alpha"))
    final_bal = updated_account.available_balance
    final_holds = updated_account.active_holds_total
    assert final_bal == 9950.0
    assert final_holds == 0.0


def test_budget_release_cqrs(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify ReleaseBudgetCommand cancels hold in full without billing."""
    _, pipeline = hermetic_cqrs_pipeline

    reserve_res = pipeline.execute(
        ReserveBudgetCommand(
            tenant_id="tenant-beta",
            job_id="job-202",
            estimated_credits=200.0,
        )
    )
    res_id = reserve_res["reservation_id"]

    release_res = pipeline.execute(ReleaseBudgetCommand(reservation_id=res_id))
    rel_status = release_res["status"]
    assert rel_status == "RELEASED"

    account = pipeline.execute(GetTenantBalanceQuery(tenant_id="tenant-beta"))
    bal = account.available_balance
    holds = account.active_holds_total
    assert bal == 10000.0
    assert holds == 0.0


def test_cluster_health_query(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify GetClusterHealthQuery handler aggregation."""
    _, pipeline = hermetic_cqrs_pipeline

    report = pipeline.execute(GetClusterHealthQuery())
    healthy = report.healthy_nodes_count
    cpus = report.total_cpus
    assert healthy >= 0
    assert cpus >= 0
