"""Tests for monopoly domain models."""

import pytest

from monopoly.domain.models import (
    PreemptionAuditRecord,
    SimulationPhaseResult,
    TenantWorkload,
)


def test_tenant_workload_creation() -> None:
    """Verify TenantWorkload field validation and defaults."""
    workload = TenantWorkload(
        tenant_id="team_alpha",
        shares=1.0,
        job_count=100,
        checkpointable=True,
        walltime_seconds=300.0,
    )
    t_id = workload.tenant_id
    assert t_id == "team_alpha"
    shares = workload.shares
    assert shares == 1.0
    jobs = workload.job_count
    assert jobs == 100
    chk = workload.checkpointable
    assert chk is True
    walltime = workload.walltime_seconds
    assert walltime == 300.0

    with pytest.raises(ValueError):
        TenantWorkload(tenant_id="", job_count=10)

    with pytest.raises(ValueError):
        TenantWorkload(tenant_id="team_alpha", job_count=0)


def test_preemption_audit_record() -> None:
    """Verify PreemptionAuditRecord fields and validation."""
    record = PreemptionAuditRecord(
        preempted_job_id="alpha-job-001",
        victim_tenant="team_alpha",
        starved_tenant="team_beta",
        reason="fair-share starvation",
        timestamp=1700000000.0,
        compensation_bonus=5000.0,
    )
    job_id = record.preempted_job_id
    assert job_id == "alpha-job-001"
    victim = record.victim_tenant
    assert victim == "team_alpha"
    starved = record.starved_tenant
    assert starved == "team_beta"
    bonus = record.compensation_bonus
    assert bonus == 5000.0


def test_simulation_phase_result() -> None:
    """Verify SimulationPhaseResult fields."""
    phase = SimulationPhaseResult(
        phase_name="Phase 1",
        elapsed_seconds=10.0,
        used_slots=100,
        available_slots=0,
        slots_tenant_a=100,
        slots_tenant_b=0,
        pending_jobs_count=1,
        preempted_jobs_count=0,
        notes="Testing phase",
    )
    name = phase.phase_name
    assert name == "Phase 1"
    used = phase.used_slots
    assert used == 100
    avail = phase.available_slots
    assert avail == 0
    slots_a = phase.slots_tenant_a
    assert slots_a == 100
    slots_b = phase.slots_tenant_b
    assert slots_b == 0
