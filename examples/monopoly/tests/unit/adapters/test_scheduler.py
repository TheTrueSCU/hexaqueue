"""Tests for BatchSchedulerClusterSimulator."""

from monopoly.adapters.scheduler import BatchSchedulerClusterSimulator
from monopoly.domain.models import TenantWorkload


def test_batch_scheduler_simulation_full_lifecycle() -> None:
    """Verify simulation adapter lifecycle through all three phases."""
    sim = BatchSchedulerClusterSimulator(
        total_slots=100,
        grace_period_seconds=30.0,
        starvation_deficit_threshold=0.4,
        preemption_bonus=5000.0,
    )

    t_a = TenantWorkload(
        tenant_id="alpha", shares=1.0, job_count=100, checkpointable=True
    )
    t_b = TenantWorkload(
        tenant_id="beta", shares=1.0, job_count=1, checkpointable=False
    )
    sim.setup_tenants(t_a, t_b)

    # Phase 1: 100 slots monopoly
    p1 = sim.run_monopoly_phase()
    used_1 = p1.used_slots
    assert used_1 == 100
    avail_1 = p1.available_slots
    assert avail_1 == 0
    slots_a_1 = p1.slots_tenant_a
    assert slots_a_1 == 100
    slots_b_1 = p1.slots_tenant_b
    assert slots_b_1 == 0

    # Phase 2: Starvation under grace period (10s < 30s)
    p2 = sim.run_starvation_phase(elapsed_seconds=10.0)
    pending_2 = p2.pending_jobs_count
    assert pending_2 == 1
    preempted_2 = p2.preempted_jobs_count
    assert preempted_2 == 0
    slots_a_2 = p2.slots_tenant_a
    assert slots_a_2 == 100

    # Phase 3: Preemption after grace period (35s > 30s)
    p3 = sim.run_preemption_phase(elapsed_seconds=35.0)
    pending_3 = p3.pending_jobs_count
    assert pending_3 == 0
    preempted_3 = p3.preempted_jobs_count
    assert preempted_3 == 1
    slots_a_3 = p3.slots_tenant_a
    assert slots_a_3 == 99
    slots_b_3 = p3.slots_tenant_b
    assert slots_b_3 == 1

    # Invariant: Conservation of total slots (99 + 1 = 100)
    used_3 = p3.used_slots
    assert used_3 == 100

    audit = sim.get_audit_log()
    audit_len = len(audit)
    assert audit_len == 1
    first_audit = audit[0]
    victim = first_audit.victim_tenant
    assert victim == "alpha"
    starved = first_audit.starved_tenant
    assert starved == "beta"
    bonus = first_audit.compensation_bonus
    assert bonus == 5000.0


def test_batch_scheduler_reinitialize() -> None:
    """Verify initialize_cluster resets state."""
    sim = BatchSchedulerClusterSimulator(total_slots=50)
    p1 = sim.run_monopoly_phase()
    used_before = p1.used_slots
    assert used_before == 50

    sim.initialize_cluster(total_slots=20)
    audit_after = sim.get_audit_log()
    audit_count = len(audit_after)
    assert audit_count == 0
    tot_slots = sim.total_slots
    assert tot_slots == 20
