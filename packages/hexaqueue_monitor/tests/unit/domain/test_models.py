"""Unit tests for monitor domain models re-exported and utilized in hexaqueue_monitor."""

from hexaqueue_monitor.domain.models import (
    BudgetReservation,
    ClusterHealthReport,
    NodeHealthState,
    ReservationState,
    TenantAccount,
)


def test_monitor_domain_models_importable() -> None:
    """Verify monitor domain models can be instantiated."""
    res = BudgetReservation(
        tenant_id="tenant-1",
        job_id="job-1",
        held_credits=50.0,
    )
    assert res.state == ReservationState.ACTIVE
    assert res.held_credits == 50.0

    acct = TenantAccount(
        tenant_id="tenant-1",
        credit_balance=100.0,
        active_holds_total=50.0,
    )
    assert acct.available_balance == 50.0

    report = ClusterHealthReport(
        healthy_nodes_count=2,
        unhealthy_nodes_count=0,
        dead_nodes_count=0,
        total_cpus=16,
        allocated_cpus=8,
        total_ram_mb=32768,
        allocated_ram_mb=16384,
        total_gpus=2,
        allocated_gpus=1,
        active_jobs_count=4,
    )
    assert report.healthy_nodes_count == 2
    assert NodeHealthState.HEALTHY == "HEALTHY"


__all__ = [
    "test_monitor_domain_models_importable",
]
