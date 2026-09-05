"""Main CLI entrypoint for hexaqueue (hq).

Notes/Architectural Intent:
    Root Typer application dispatching subcommands and top-level helpers (status, list, logs, cancel).
"""

import asyncio

import typer
from rich.console import Console
from rich.table import Table

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.commands.run import app as run_app

app = typer.Typer(
    name="hq",
    help="Hexaqueue - Cloud-Agnostic HPC Batch Scheduler and Distributed Job Orchestrator",
    no_args_is_help=True,
)
app.add_typer(run_app, name="run")

console = Console()


@app.command("status")
def status_cmd(
    target_id: str = typer.Argument(..., help="Run ID or Job ID to inspect"),
) -> None:
    """Check status of a run or job."""

    async def _status() -> None:
        client = LocalClientAdapter()
        try:
            report = await client.get_run_status(target_id)
            table = Table(title=f"Run Status: {report.run_id}")
            table.add_column("Run ID", style="cyan")
            table.add_column("State", style="magenta")
            table.add_column(
                "Outcome",
                style="green"
                if report.outcome in ("COMPLETED", "SUCCEEDED")
                else "yellow",
            )
            table.add_column("Total", justify="center")
            table.add_column("Completed", justify="center", style="green")
            table.add_column("Failed", justify="center", style="red")
            table.add_column("Pending", justify="center", style="yellow")
            table.add_row(
                report.run_id,
                report.state.value
                if hasattr(report.state, "value")
                else str(report.state),
                str(report.outcome) if report.outcome else "-",
                str(report.total_jobs),
                str(report.completed_jobs),
                str(report.failed_jobs),
                str(report.pending_jobs),
            )
            console.print(table)
            return
        except Exception:
            pass

        try:
            job = await client.get_job(target_id)
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
                job.state.value if hasattr(job.state, "value") else str(job.state),
                str(job.outcome) if job.outcome else "-",
            )
            console.print(table)
        except Exception as e:
            console.print(f"[bold red]Error querying status for '{target_id}':[/] {e}")
            raise typer.Exit(code=1) from e

    asyncio.run(_status())


@app.command("logs")
def logs_cmd(
    job_id: str = typer.Argument(..., help="Job ID to fetch logs for"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow stream output"),
) -> None:
    """View stdout and stderr logs for a job."""

    async def _logs() -> None:
        client = LocalClientAdapter()
        logs = await client.get_logs(job_id)
        if not logs:
            console.print(f"[dim]No logs recorded for job '{job_id}'[/]")
            return
        for chunk in logs:
            prefix = f"[{chunk.stream}] " if chunk.stream != "stdout" else ""
            console.print(f"{prefix}{chunk.content}", end="")

    asyncio.run(_logs())


@app.command("cancel")
def cancel_cmd(
    run_id: str = typer.Argument(..., help="Run ID to cancel"),
) -> None:
    """Cancel an active pipeline run."""

    async def _cancel() -> None:
        client = LocalClientAdapter()
        try:
            report = await client.cancel_run(run_id)
            console.print(f"[bold yellow]✓[/] Run '{report.run_id}' cancelled.")
        except Exception as e:
            console.print(f"[bold red]Error cancelling run '{run_id}':[/] {e}")
            raise typer.Exit(code=1) from e

    asyncio.run(_cancel())


__all__ = [
    "app",
]
