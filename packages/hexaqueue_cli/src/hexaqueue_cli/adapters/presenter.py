"""Terminal and pipeline output presenters for Hexaqueue CLI commands.

Notes/Architectural Intent:
    Provides formatted output rendering across multiple formats (table, json, markdown, plain, rich).
    Ensures seamless piping into downstream Unix utilities when non-interactive, while
    delivering rich visual dashboards for human terminal operators.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from pydantic import BaseModel
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from hexaqueue_cli.domain.options import OutputFormat
from hexaqueue_core.domain.explainability import (
    FairShareNodeReport,
    FairShareTreeReport,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.freetier import FreeTierBurnReport
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_server.domain.models import RunStatusReport

__all__ = [
    "CliPresenter",
]


class CliPresenter:
    """Presenter formatting CLI models and reports across supported output formats.

    Notes/Architectural Intent:
        Implements rendering for table, json, markdown, plain, and rich.
        Allows commands to dispatch results cleanly without mixing presentation logic
        with orchestration.
    """

    def __init__(
        self,
        console: Console | None = None,
        stderr_console: Console | None = None,
    ) -> None:
        """Initialize CliPresenter with optional consoles.

        Args:
            console: Optional Rich console for stdout.
            stderr_console: Optional Rich console for stderr.
        """
        no_color = bool(os.environ.get("NO_COLOR"))
        self._console = console or Console(no_color=no_color, highlight=not no_color)
        self._stderr = stderr_console or Console(
            stderr=True, no_color=no_color, highlight=not no_color
        )

    def render_run_status(
        self,
        report: RunStatusReport,
        format_type: str | OutputFormat = OutputFormat.TABLE,
    ) -> None:
        """Render a pipeline run status report in the chosen format.

        Args:
            report: RunStatusReport domain model.
            format_type: Chosen output format string or OutputFormat enum.
        """
        fmt = (
            format_type.value
            if isinstance(format_type, OutputFormat)
            else str(format_type).lower().strip()
        )

        data = {
            "run_id": report.run_id,
            "state": (
                report.state.value
                if hasattr(report.state, "value")
                else str(report.state)
            ),
            "outcome": (
                report.outcome.value
                if hasattr(report.outcome, "value")
                else (str(report.outcome) if report.outcome else None)
            ),
            "total_jobs": report.total_jobs,
            "completed_jobs": report.completed_jobs,
            "failed_jobs": report.failed_jobs,
            "pending_jobs": report.pending_jobs,
        }
        if report.free_tier_active:
            data["free_tier_active"] = True
        if report.burn_report is not None:
            data["burn_report"] = report.burn_report.model_dump()

        if fmt == OutputFormat.JSON.value:
            sys.stdout.write(json.dumps(data, indent=2) + "\n")
            sys.stdout.flush()
        elif fmt == OutputFormat.MARKDOWN.value:
            lines = [
                f"### Run Status: {report.run_id}",
                "",
                "| Field | Value |",
                "|---|---|",
                f"| Run ID | `{report.run_id}` |",
                f"| State | **{data['state']}** |",
                f"| Outcome | {data['outcome'] or '-'} |",
                f"| Total Jobs | {report.total_jobs} |",
                f"| Completed | {report.completed_jobs} |",
                f"| Failed | {report.failed_jobs} |",
                f"| Pending | {report.pending_jobs} |",
            ]
            if report.free_tier_active:
                lines.insert(0, "> **[FREE TIER ACTIVE]** Zero-Cost Guard Active\n")
            if report.burn_report is not None:
                b = report.burn_report
                lines.extend(
                    [
                        "",
                        f"#### Free-Tier Quota Burn ({b.profile_name})",
                        "",
                        "| Resource | Allocated | Ceiling | Utilization |",
                        "|---|---|---|---|",
                        f"| CPU | {b.allocated_cpus} cores | {b.cpu_ceiling} cores | {b.cpu_utilization_pct}% |",
                        f"| RAM | {b.allocated_ram_mb} MB | {b.ram_ceiling_mb} MB | {b.ram_utilization_pct}% |",
                        f"| Storage | {b.allocated_storage_mb} MB | {b.storage_ceiling_mb} MB | {b.storage_utilization_pct}% |",
                    ]
                )
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()
        elif fmt == OutputFormat.PLAIN.value:
            for k, v in data.items():
                sys.stdout.write(f"{k}\t{v}\n")
            sys.stdout.flush()
        else:
            # table or rich
            title = f"Run Status: {report.run_id}"
            if report.free_tier_active:
                title = f"[bold green][FREE TIER ACTIVE][/] {title}"
            table = Table(title=title)
            table.add_column("Run ID", style="cyan")
            table.add_column("State", style="magenta")
            table.add_column(
                "Outcome",
                style="green"
                if str(report.outcome) in ("COMPLETED", "SUCCEEDED")
                else "yellow",
            )
            table.add_column("Total", justify="center")
            table.add_column("Completed", justify="center", style="green")
            table.add_column("Failed", justify="center", style="red")
            table.add_column("Pending", justify="center", style="yellow")
            table.add_row(
                report.run_id,
                data["state"],
                str(report.outcome) if report.outcome else "-",
                str(report.total_jobs),
                str(report.completed_jobs),
                str(report.failed_jobs),
                str(report.pending_jobs),
            )
            self._console.print(table)
            if report.burn_report is not None:
                self._render_burn_meter(report.burn_report)

    def _render_burn_meter(self, burn: FreeTierBurnReport) -> None:
        """Render Rich table visualizing free-tier resource burn meters."""
        burn_table = Table(
            title=f"Free-Tier Quota Burn Meter ({burn.profile_name})",
            style="green",
        )
        burn_table.add_column("Resource", style="cyan")
        burn_table.add_column("Allocated", justify="right")
        burn_table.add_column("Ceiling", justify="right")
        burn_table.add_column("Utilization", justify="right", style="yellow")
        burn_table.add_column("Status", justify="center")

        cpu_status = (
            "[bold red]THROTTLED[/]"
            if burn.is_throttled and burn.cpu_utilization_pct >= 100.0
            else "[green]OK[/]"
        )
        ram_status = (
            "[bold red]THROTTLED[/]"
            if burn.is_throttled and burn.ram_utilization_pct >= 100.0
            else "[green]OK[/]"
        )
        storage_status = "[green]OK[/]"

        burn_table.add_row(
            "CPU",
            f"{burn.allocated_cpus} cores",
            f"{burn.cpu_ceiling} cores",
            f"{burn.cpu_utilization_pct}%",
            cpu_status,
        )
        burn_table.add_row(
            "RAM",
            f"{burn.allocated_ram_mb} MB",
            f"{burn.ram_ceiling_mb} MB",
            f"{burn.ram_utilization_pct}%",
            ram_status,
        )
        burn_table.add_row(
            "Storage",
            f"{burn.allocated_storage_mb} MB",
            f"{burn.storage_ceiling_mb} MB",
            f"{burn.storage_utilization_pct}%",
            storage_status,
        )
        self._console.print(burn_table)

    def render_job(
        self,
        job: JobSpec,
        format_type: str | OutputFormat = OutputFormat.TABLE,
    ) -> None:
        """Render a single JobSpec in the chosen format.

        Args:
            job: JobSpec domain model.
            format_type: Chosen output format string or OutputFormat enum.
        """
        fmt = (
            format_type.value
            if isinstance(format_type, OutputFormat)
            else str(format_type).lower().strip()
        )

        state_val = job.state.value if hasattr(job.state, "value") else str(job.state)
        outcome_val = (
            job.outcome.value
            if hasattr(job.outcome, "value")
            else (str(job.outcome) if job.outcome else None)
        )

        data = {
            "id": job.id,
            "run_id": job.run_id,
            "name": job.name,
            "state": state_val,
            "outcome": outcome_val,
            "command": job.command,
        }

        if fmt == OutputFormat.JSON.value:
            sys.stdout.write(json.dumps(data, indent=2) + "\n")
            sys.stdout.flush()
        elif fmt == OutputFormat.MARKDOWN.value:
            lines = [
                f"### Job Status: {job.id}",
                "",
                "| Field | Value |",
                "|---|---|",
                f"| Job ID | `{job.id}` |",
                f"| Run ID | `{job.run_id}` |",
                f"| Name | {job.name} |",
                f"| State | **{state_val}** |",
                f"| Outcome | {outcome_val or '-'} |",
                f"| Command | `{job.command}` |",
            ]
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()
        elif fmt == OutputFormat.PLAIN.value:
            for k, v in data.items():
                sys.stdout.write(f"{k}\t{v}\n")
            sys.stdout.flush()
        else:
            table = Table(title=f"Job Status: {job.id}")
            table.add_column("Job ID", style="cyan")
            table.add_column("Run ID", style="blue")
            table.add_column("Name")
            table.add_column("State", style="magenta")
            table.add_column("Outcome")
            table.add_row(
                job.id,
                job.run_id,
                job.name,
                state_val,
                str(job.outcome) if job.outcome else "-",
            )
            self._console.print(table)

    def _serialize_checkpoints(self, checkpoints: list[Any]) -> list[dict[str, Any]]:
        """Extract serialized dictionary representations of step checkpoints."""
        chk_list: list[dict[str, Any]] = []
        for chk in checkpoints:
            chk_status = (
                chk.status.value if hasattr(chk.status, "value") else str(chk.status)
            )
            payload = (
                chk.output_payload
                if not isinstance(chk.output_payload, BaseModel)
                else chk.output_payload.model_dump()
            )
            chk_list.append(
                {
                    "stage_name": chk.stage_name,
                    "step_name": chk.step_name,
                    "status": chk_status,
                    "attempt_number": chk.attempt_number,
                    "duration_seconds": round(chk.duration_seconds, 3),
                    "output_payload": payload,
                }
            )
        return chk_list

    def _render_workflow_json(self, data: dict[str, Any]) -> None:
        """Output workflow status report as indented JSON."""
        sys.stdout.write(json.dumps(data, indent=2, default=str) + "\n")
        sys.stdout.flush()

    def _render_workflow_markdown(self, data: dict[str, Any]) -> None:
        """Output workflow status report as Markdown."""
        lines = [
            f"### Workflow Run: {data['workflow_name']} (`{data['run_id']}`)",
            "",
            f"- **Status**: `{data['status']}`",
        ]
        if data.get("current_stage"):
            lines.append(f"- **Current Stage**: {data['current_stage']}")
        if data.get("error_summary"):
            lines.append(f"- **Error**: {data['error_summary']}")
        lines.extend(
            [
                "",
                "| Stage | Step | Status | Attempt | Duration (s) |",
                "|---|---|---|---|---|",
            ]
        )
        for c in data.get("checkpoints", []):
            lines.append(
                f"| {c['stage_name']} | {c['step_name']} | {c['status']} | {c['attempt_number']} | {c['duration_seconds']} |"
            )
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()

    def _render_workflow_plain(self, data: dict[str, Any]) -> None:
        """Output workflow status report as plain tab-delimited text."""
        sys.stdout.write(f"run_id\t{data['run_id']}\n")
        sys.stdout.write(f"workflow\t{data['workflow_name']}\n")
        sys.stdout.write(f"status\t{data['status']}\n")
        for c in data.get("checkpoints", []):
            sys.stdout.write(
                f"{c['stage_name']}\t{c['step_name']}\t{c['status']}\t{c['duration_seconds']}\n"
            )
        sys.stdout.flush()

    def _render_workflow_table(self, data: dict[str, Any]) -> None:
        """Output workflow status report as interactive Rich table and panel."""
        header_table = Table.grid(padding=(0, 2))
        header_table.add_column(style="bold")
        header_table.add_column()
        header_table.add_row("Run ID:", str(data["run_id"]))
        header_table.add_row("Workflow:", str(data["workflow_name"]))
        header_table.add_row("Status:", f"[bold cyan]{data['status']}[/]")
        if data.get("current_stage"):
            header_table.add_row("Current Stage:", str(data["current_stage"]))
        if data.get("error_summary"):
            header_table.add_row("Error:", f"[bold red]{data['error_summary']}[/]")

        self._console.print(
            Panel(
                header_table,
                title=f"Workflow Run: {data['workflow_name']}",
                expand=False,
            )
        )

        chk_list = data.get("checkpoints", [])
        if not chk_list:
            self._console.print("[dim]No step checkpoints recorded yet.[/]")
            return

        table = Table(title="Step Checkpoints & Staged Artifacts", expand=True)
        table.add_column("Stage", style="cyan")
        table.add_column("Step", style="bold")
        table.add_column("Status", justify="center")
        table.add_column("Attempt", justify="right")
        table.add_column("Duration (s)", justify="right")
        table.add_column("Artifact / Output", style="dim")

        for chk in chk_list:
            chk_color = (
                "[green]COMPLETED[/]"
                if chk["status"] == "COMPLETED"
                else (
                    "[red]FAILED[/]"
                    if chk["status"] == "FAILED"
                    else str(chk["status"])
                )
            )
            payload_repr = str(chk["output_payload"])
            if len(payload_repr) > 30:
                payload_repr = payload_repr[:30] + "..."

            table.add_row(
                chk["stage_name"],
                chk["step_name"],
                chk_color,
                str(chk["attempt_number"]),
                f"{chk['duration_seconds']:.3f}",
                payload_repr,
            )
        self._console.print(table)

    def render_workflow_state(
        self,
        state: Any,
        checkpoints: list[Any],
        format_type: str | OutputFormat = OutputFormat.TABLE,
    ) -> None:
        """Render workflow execution state and checkpoints in the chosen format.

        Args:
            state: WorkflowExecutionState instance.
            checkpoints: List of CheckpointRecord instances.
            format_type: Chosen output format string or OutputFormat enum.
        """
        fmt = (
            format_type.value
            if isinstance(format_type, OutputFormat)
            else str(format_type).lower().strip()
        )
        status_val = (
            state.status.value if hasattr(state.status, "value") else str(state.status)
        )
        data = {
            "run_id": state.run_id,
            "workflow_name": state.workflow_name,
            "status": status_val,
            "current_stage": getattr(state, "current_stage", None),
            "error_summary": getattr(state, "error_summary", None),
            "checkpoints": self._serialize_checkpoints(checkpoints),
        }

        if fmt == OutputFormat.JSON.value:
            self._render_workflow_json(data)
        elif fmt == OutputFormat.MARKDOWN.value:
            self._render_workflow_markdown(data)
        elif fmt == OutputFormat.PLAIN.value:
            self._render_workflow_plain(data)
        else:
            self._render_workflow_table(data)

    def render_why_summary(self, report: SchedulingDecisionReport) -> None:
        """Render concise one-liner explanation of why a job is pending or running.

        Args:
            report: SchedulingDecisionReport instance.
        """
        prefix = (
            "[bold yellow]Why Pending:[/] "
            if report.queue_position > 0
            else "[bold green]Status:[/] "
        )
        self._console.print(f"{prefix}{report.summary}")

    def render_explain_report(
        self,
        report: SchedulingDecisionReport,
        format_type: str | OutputFormat = OutputFormat.TABLE,
    ) -> None:
        """Render granular scheduling decision and priority breakdown report.

        Args:
            report: SchedulingDecisionReport instance.
            format_type: Chosen output format string or OutputFormat enum.
        """
        fmt = (
            format_type.value
            if isinstance(format_type, OutputFormat)
            else str(format_type).lower().strip()
        )
        if fmt == OutputFormat.JSON.value:
            self._console.print(report.model_dump_json(indent=2))
        elif fmt == OutputFormat.PLAIN.value:
            self._render_explain_plain(report)
        else:
            self._render_explain_table(report)

    def _render_explain_plain(self, report: SchedulingDecisionReport) -> None:
        bd = report.priority_breakdown
        lines = [
            f"Job ID: {report.job_id}",
            f"User: {report.user}",
            f"State: {report.state}",
            f"Queue Position: #{report.queue_position} of {report.queue_total}",
            f"Total Priority: {bd.total_priority}",
            f"  Base Score: {bd.base_score}",
            f"  Age Score: {bd.age_score} ({bd.age_seconds}s)",
            f"  Fair-Share Score: {bd.fairshare_score} (F={bd.fairshare_factor})",
            f"  Preemption Bonus: {bd.preemption_bonus}",
            f"Required Slots: {report.required_slots} (Available: {report.available_slots}/{report.total_slots})",
            f"Summary: {report.summary}",
        ]
        self._console.print("\n".join(lines))

    def _render_explain_table(self, report: SchedulingDecisionReport) -> None:
        table = Table(title=f"Scheduling Decision Report: {report.job_id}", expand=True)
        table.add_column("Metric / Dimension", style="bold cyan")
        table.add_column("Value", style="green")

        bd = report.priority_breakdown
        table.add_row("User / Owner", report.user)
        table.add_row("Lifecycle State", str(report.state))
        table.add_row("Queue Rank", f"#{report.queue_position} of {report.queue_total}")
        table.add_row(
            "Slots Required / Avail / Total",
            f"{report.required_slots} / {report.available_slots} / {report.total_slots}",
        )
        if report.blocking_anchor_id:
            table.add_row("Blocking Anchor Job", report.blocking_anchor_id)
        if report.estimated_wait_seconds is not None:
            table.add_row("Estimated Wait", f"{report.estimated_wait_seconds:.1f}s")
        table.add_row(
            "Total Priority Score",
            f"[bold yellow]{bd.total_priority:.2f}[/]",
        )
        table.add_row("  └ Base Score", f"{bd.base_score:.2f}")
        table.add_row(
            "  └ Age Score",
            f"{bd.age_score:.2f} (waiting {bd.age_seconds:.0f}s)",
        )
        table.add_row(
            "  └ Fair-Share Score",
            f"{bd.fairshare_score:.2f} (F={bd.fairshare_factor:.4f}, share={bd.target_share:.2%})",
        )
        table.add_row("  └ Preemption Bonus", f"{bd.preemption_bonus:.2f}")

        for idx, r in enumerate(report.pending_reasons, start=1):
            table.add_row(f"Blocker #{idx} ({r.code.value})", r.message)

        self._console.print(table)
        self._console.print(
            Panel(report.summary, title="Summary Reason", border_style="yellow")
        )

    def render_fairshare_tree(
        self,
        report: FairShareTreeReport,
        format_type: str | OutputFormat = OutputFormat.TABLE,
    ) -> None:
        """Render hierarchical fair-share tree in chosen format.

        Args:
            report: FairShareTreeReport instance.
            format_type: Chosen output format.
        """
        fmt = (
            format_type.value
            if isinstance(format_type, OutputFormat)
            else str(format_type).lower().strip()
        )
        if fmt == OutputFormat.JSON.value:
            self._console.print(report.model_dump_json(indent=2))
        else:
            days = report.half_life_seconds / 86400.0
            rich_tree = Tree(
                f"[bold cyan]Root Hierarchy[/] (Decay Half-Life: {days:.1f} days, "
                f"Total Usage: {report.total_decayed_usage:.1f})"
            )
            self._populate_rich_tree(report.root, rich_tree)
            self._console.print(rich_tree)

    def _populate_rich_tree(self, node: FairShareNodeReport, parent_tree: Tree) -> None:
        for child in node.children:
            label = (
                f"[bold green]{child.id}[/] | shares={child.shares:.1f} | "
                f"target={child.target_share:.1%} | usage={child.decayed_usage:.1f} | "
                f"Factor F=[bold yellow]{child.fairshare_factor:.4f}[/]"
            )
            child_tree = parent_tree.add(label)
            self._populate_rich_tree(child, child_tree)
