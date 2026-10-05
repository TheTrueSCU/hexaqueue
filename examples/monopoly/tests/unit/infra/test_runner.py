"""Tests for monopoly simulation runner and presenter."""

from io import StringIO

from rich.console import Console

from monopoly.infra.runner import render_monopoly_report, run_monopoly_simulation


def test_run_monopoly_simulation() -> None:
    """Verify run_monopoly_simulation returns 3 phases and audit events."""
    phases, audit = run_monopoly_simulation(
        total_slots=100,
        grace_period_seconds=30.0,
        starvation_deficit_threshold=0.4,
        preemption_bonus=5000.0,
    )
    phase_count = len(phases)
    assert phase_count == 3
    audit_count = len(audit)
    assert audit_count == 1

    p1, p2, p3 = phases
    p1_a = p1.slots_tenant_a
    assert p1_a == 100
    p2_pend = p2.pending_jobs_count
    assert p2_pend == 1
    p3_preempt = p3.preempted_jobs_count
    assert p3_preempt == 1
    p3_b = p3.slots_tenant_b
    assert p3_b == 1


def test_render_monopoly_report() -> None:
    """Verify render_monopoly_report outputs expected Rich tables."""
    phases, audit = run_monopoly_simulation(
        total_slots=50,
        grace_period_seconds=30.0,
        starvation_deficit_threshold=0.4,
        preemption_bonus=5000.0,
    )
    buffer = StringIO()
    console = Console(file=buffer, color_system=None)
    render_monopoly_report(phases, audit, console=console)
    output = buffer.getvalue()
    has_title = "100-Slot Cluster Monopoly Resolution Lifecycle" in output
    assert has_title is True
    has_audit_title = "Controlled Preemption Audit Trail" in output
    assert has_audit_title is True
    has_guardrails = "Hexaqueue Scheduling Guardrails Verified" in output
    assert has_guardrails is True
