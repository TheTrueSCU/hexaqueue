"""Test hexaqueue_monitor package exports."""

import hexaqueue_monitor
from hexaqueue_monitor import (
    DEFAULT_PROVIDER_RATES,
    BudgetReservation,
    ClusterHealthReport,
    ClusterMonitorPort,
    ExecutionSegmentRecord,
    GpuTelemetry,
    InMemoryBudgetLedgerAdapter,
    LocalClusterMonitorAdapter,
    MonitorConfig,
    MonitorDaemon,
    NodeHealthState,
    NodeTelemetryPulse,
    NormalizedCostRateModelAdapter,
    ReservationState,
    TenantAccount,
)


def test_hexaqueue_monitor_package_exports() -> None:
    """Verify package public API exports."""
    assert hexaqueue_monitor is not None
    assert BudgetReservation is not None
    assert ClusterHealthReport is not None
    assert ClusterMonitorPort is not None
    assert DEFAULT_PROVIDER_RATES is not None
    assert ExecutionSegmentRecord is not None
    assert GpuTelemetry is not None
    assert InMemoryBudgetLedgerAdapter is not None
    assert LocalClusterMonitorAdapter is not None
    assert MonitorConfig is not None
    assert MonitorDaemon is not None
    assert NodeHealthState is not None
    assert NodeTelemetryPulse is not None
    assert NormalizedCostRateModelAdapter is not None
    assert ReservationState is not None
    assert TenantAccount is not None


__all__ = [
    "test_hexaqueue_monitor_package_exports",
]
