"""Abstract port interface for cluster monopoly simulation.

Notes/Architectural Intent:
    Defines the contract for initializing multi-tenant slot pools, configuring
    fair-share trees, running scheduler simulation phases, and extracting audit logs.
"""

from abc import ABC, abstractmethod

from monopoly.domain.models import (
    PreemptionAuditRecord,
    SimulationPhaseResult,
    TenantWorkload,
)


class ClusterSimulatorPort(ABC):
    """Abstract cluster simulation port interface."""

    @abstractmethod
    def initialize_cluster(self, total_slots: int = 100) -> None:
        """Initialize the cluster resource pool with specified slot capacity.

        Args:
            total_slots: Total slot capacity of the cluster.
        """

    @abstractmethod
    def setup_tenants(self, tenant_a: TenantWorkload, tenant_b: TenantWorkload) -> None:
        """Configure fair-share tree and tenants for the simulation.

        Args:
            tenant_a: Workload and entitlement spec for Tenant A.
            tenant_b: Workload and entitlement spec for Tenant B.
        """

    @abstractmethod
    def run_monopoly_phase(self) -> SimulationPhaseResult:
        """Execute Phase 1: Tenant A occupies all 100 cluster slots.

        Returns:
            Snapshot of cluster allocation and queue state.
        """

    @abstractmethod
    def run_starvation_phase(
        self, elapsed_seconds: float = 10.0
    ) -> SimulationPhaseResult:
        """Execute Phase 2: Tenant B submits urgent jobs during grace period.

        Args:
            elapsed_seconds: Wait time elapsed (< grace period).

        Returns:
            Snapshot showing Tenant B jobs waiting safely without thrashing.
        """

    @abstractmethod
    def run_preemption_phase(
        self, elapsed_seconds: float = 35.0
    ) -> SimulationPhaseResult:
        """Execute Phase 3: Grace period expires and controlled preemption triggers.

        Args:
            elapsed_seconds: Wait time elapsed (> grace period).

        Returns:
            Snapshot showing preemption of Tenant A victim and allocation of Tenant B.
        """

    @abstractmethod
    def get_audit_log(self) -> list[PreemptionAuditRecord]:
        """Retrieve historical preemption audit records.

        Returns:
            List of recorded preemption events.
        """


__all__ = [
    "ClusterSimulatorPort",
]
