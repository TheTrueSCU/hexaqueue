"""Main CLI entrypoint for hexaqueue (hq).

Notes/Architectural Intent:
    Root Typer application dispatching subcommands and top-level helpers (status, list, logs, cancel).
"""

import asyncio

import typer
from rich.console import Console

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.adapters.presenter import CliPresenter
from hexaqueue_cli.commands.run import app as run_app
from hexaqueue_cli.commands.workflow import app as workflow_app
from hexaqueue_cli.infra.options import format_option, resolve_format

app = typer.Typer(
    name="hq",
    help="Hexaqueue - Cloud-Agnostic HPC Batch Scheduler and Distributed Job Orchestrator",
    no_args_is_help=True,
)
app.add_typer(run_app, name="run")
app.add_typer(workflow_app, name="workflow")

console = Console()


@app.command("status")
def status_cmd(
    target_id: str = typer.Argument(..., help="Run ID or Job ID to inspect"),
    format_type: str = format_option(),
) -> None:
    """Check status of a run or job."""
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _status() -> None:
        client = LocalClientAdapter()
        try:
            report = await client.get_run_status(target_id)
            presenter.render_run_status(report, resolved_fmt)
            return
        except Exception:
            pass

        try:
            job = await client.get_job(target_id)
            presenter.render_job(job, resolved_fmt)
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
