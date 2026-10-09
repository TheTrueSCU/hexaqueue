"""Domain models for cluster monitoring and budget accounting.

Notes/Architectural Intent:
    Re-exports core budget and telemetry models within the monitor domain layer
    to preserve clean hexagonal boundaries while avoiding duplication.
"""

from hexaqueue_core.domain.budget import (
    BudgetReservation,
    ClusterHealthReport,
    ExecutionSegmentRecord,
    ReservationState,
    TenantAccount,
)
from hexaqueue_core.domain.node import NodeHealthState
from hexaqueue_core.domain.telemetry import (
    GpuTelemetry,
    NodeTelemetryPulse,
)

__all__ = [
    "BudgetReservation",
    "ClusterHealthReport",
    "ExecutionSegmentRecord",
    "GpuTelemetry",
    "NodeHealthState",
    "NodeTelemetryPulse",
    "ReservationState",
    "TenantAccount",
]
