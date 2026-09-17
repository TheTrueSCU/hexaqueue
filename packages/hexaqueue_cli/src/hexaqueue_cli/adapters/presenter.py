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

from hexaqueue_cli.domain.options import OutputFormat
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
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()
        elif fmt == OutputFormat.PLAIN.value:
            for k, v in data.items():
                sys.stdout.write(f"{k}\t{v}\n")
            sys.stdout.flush()
        else:
            # table or rich
            table = Table(title=f"Run Status: {report.run_id}")
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
