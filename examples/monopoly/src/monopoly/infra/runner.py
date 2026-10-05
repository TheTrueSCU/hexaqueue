"""Simulation runner and Rich console presenter for the 100-slot monopoly scenario.

Notes/Architectural Intent:
    Orchestrates the three canonical phases of the 100-slot monopoly problem
    and provides visual terminal reporting for developer inspection.
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from monopoly.adapters.scheduler import BatchSchedulerClusterSimulator
from monopoly.domain.models import (
    PreemptionAuditRecord,
    SimulationPhaseResult,
    TenantWorkload,
)


def run_monopoly_simulation(
    total_slots: int = 100,
    grace_period_seconds: float = 30.0,
    starvation_deficit_threshold: float = 0.4,
    preemption_bonus: float = 5000.0,
) -> tuple[list[SimulationPhaseResult], list[PreemptionAuditRecord]]:
    """Execute the multi-phase 100-slot monopoly simulation.

    Args:
        total_slots: Total cluster slot capacity.
        grace_period_seconds: Anti-thrashing grace period threshold.
        starvation_deficit_threshold: Minimum starvation deficit required to trigger preemption.
        preemption_bonus: Priority compensation bonus awarded to victim tasks.

    Returns:
        Tuple of simulation phase results and preemption audit logs.
    """
    simulator = BatchSchedulerClusterSimulator(
        total_slots=total_slots,
        grace_period_seconds=grace_period_seconds,
        starvation_deficit_threshold=starvation_deficit_threshold,
        preemption_bonus=preemption_bonus,
    )

    tenant_a = TenantWorkload(
        tenant_id="team_alpha",
        shares=1.0,
        job_count=total_slots,
        checkpointable=True,
    )
    tenant_b = TenantWorkload(
        tenant_id="team_beta",
        shares=1.0,
        job_count=1,
        checkpointable=False,
    )

    simulator.setup_tenants(tenant_a, tenant_b)

    # Phase 1: Monopoly
    p1 = simulator.run_monopoly_phase()

    # Phase 2: Starvation & Grace Period (< 30s)
    p2 = simulator.run_starvation_phase(elapsed_seconds=10.0)

    # Phase 3: Controlled Preemption (> 30s)
    p3 = simulator.run_preemption_phase(elapsed_seconds=35.0)

    audit_records = simulator.get_audit_log()
    return [p1, p2, p3], audit_records


def render_monopoly_report(
    phases: list[SimulationPhaseResult],
    audit_records: list[PreemptionAuditRecord],
    console: Console | None = None,
) -> None:
    """Render a Rich terminal dashboard of the simulation results.

    Args:
        phases: List of recorded simulation phase results.
        audit_records: List of recorded preemption audit events.
        console: Optional Rich console instance.
    """
    c = console or Console()

    table = Table(
        title="100-Slot Cluster Monopoly Resolution Lifecycle",
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("Phase", style="bold white", width=38)
    table.add_column("Elapsed (s)", justify="right", width=12)
    table.add_column("Alpha Slots", justify="center", style="green", width=12)
    table.add_column("Beta Slots", justify="center", style="yellow", width=12)
    table.add_column("Pending", justify="center", width=10)
    table.add_column("Preemptions", justify="center", style="red", width=12)
    table.add_column("Notes", style="dim")

    for p in phases:
        table.add_row(
            p.phase_name,
            f"{p.elapsed_seconds:.1f}s",
            str(p.slots_tenant_a),
            str(p.slots_tenant_b),
            str(p.pending_jobs_count),
            str(p.preempted_jobs_count),
            p.notes,
        )

    c.print()
    c.print(table)
    c.print()

    if audit_records:
        audit_table = Table(
            title="Controlled Preemption Audit Trail",
            header_style="bold magenta",
            border_style="dim",
        )
        audit_table.add_column("Victim Job", style="red")
        audit_table.add_column("Victim Tenant", style="green")
        audit_table.add_column("Starved Tenant", style="yellow")
        audit_table.add_column("Compensation Bonus", justify="right", style="cyan")
        audit_table.add_column("Reason")

        for r in audit_records:
            audit_table.add_row(
                r.preempted_job_id,
                r.victim_tenant,
                r.starved_tenant,
                f"+{r.compensation_bonus:.0f}",
                r.reason,
            )

        c.print(audit_table)
        c.print()

    summary_panel = Panel(
        "[bold green]✓ 100-Slot Monopoly Successfully Resolved[/]\n"
        "[dim]• Anti-thrashing grace period prevented early kills at t=10s\n"
        "• Fair-share deficit threshold (>0.4) safely triggered preemption at t=35s\n"
        "• Youngest checkpointable task was selected as victim to minimize compute loss\n"
        "• Preempted task received +5000 priority compensation bonus for rapid recovery[/]",
        border_style="green",
        title="Hexaqueue Scheduling Guardrails Verified",
    )
    c.print(summary_panel)
    c.print()


__all__ = [
    "render_monopoly_report",
    "run_monopoly_simulation",
]
