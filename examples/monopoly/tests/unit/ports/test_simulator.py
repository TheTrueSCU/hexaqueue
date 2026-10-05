"""Tests for ClusterSimulatorPort abstract contract."""

from monopoly.domain.models import (
    PreemptionAuditRecord,
    SimulationPhaseResult,
    TenantWorkload,
)
from monopoly.ports.simulator import ClusterSimulatorPort


class DummyClusterSimulator(ClusterSimulatorPort):
    """Concrete dummy implementation for interface verification."""

    def initialize_cluster(self, total_slots: int = 100) -> None:
        pass

    def setup_tenants(self, tenant_a: TenantWorkload, tenant_b: TenantWorkload) -> None:
        pass

    def run_monopoly_phase(self) -> SimulationPhaseResult:
        return SimulationPhaseResult(
            phase_name="Dummy 1",
            elapsed_seconds=0.0,
            used_slots=100,
            available_slots=0,
            slots_tenant_a=100,
            slots_tenant_b=0,
            pending_jobs_count=0,
            preempted_jobs_count=0,
            notes="Dummy",
        )

    def run_starvation_phase(
        self, elapsed_seconds: float = 10.0
    ) -> SimulationPhaseResult:
        return SimulationPhaseResult(
            phase_name="Dummy 2",
            elapsed_seconds=elapsed_seconds,
            used_slots=100,
            available_slots=0,
            slots_tenant_a=100,
            slots_tenant_b=0,
            pending_jobs_count=1,
            preempted_jobs_count=0,
            notes="Dummy 2",
        )

    def run_preemption_phase(
        self, elapsed_seconds: float = 35.0
    ) -> SimulationPhaseResult:
        return SimulationPhaseResult(
            phase_name="Dummy 3",
            elapsed_seconds=elapsed_seconds,
            used_slots=100,
            available_slots=0,
            slots_tenant_a=99,
            slots_tenant_b=1,
            pending_jobs_count=0,
            preempted_jobs_count=1,
            notes="Dummy 3",
        )

    def get_audit_log(self) -> list[PreemptionAuditRecord]:
        return []


def test_dummy_cluster_simulator_contract() -> None:
    """Verify abstract methods can be instantiated through concrete implementation."""
    dummy = DummyClusterSimulator()
    dummy.initialize_cluster(50)
    w_a = TenantWorkload(tenant_id="a", job_count=10)
    w_b = TenantWorkload(tenant_id="b", job_count=5)
    dummy.setup_tenants(w_a, w_b)

    p1 = dummy.run_monopoly_phase()
    name_1 = p1.phase_name
    assert name_1 == "Dummy 1"

    p2 = dummy.run_starvation_phase(15.0)
    name_2 = p2.phase_name
    assert name_2 == "Dummy 2"

    p3 = dummy.run_preemption_phase(40.0)
    name_3 = p3.phase_name
    assert name_3 == "Dummy 3"

    logs = dummy.get_audit_log()
    log_len = len(logs)
    assert log_len == 0
