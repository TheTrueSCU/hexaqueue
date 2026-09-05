"""CLI commands for run submission and lifecycle management.

Notes/Architectural Intent:
    Provides subcommands for submitting YAML DAG specs, inspecting status,
    and canceling active runs with Rich terminal tables.
"""

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.domain.parser import parse_run_spec_from_file
from hexaqueue_cli.domain.session import get_default_session
from hexaqueue_core.domain.lifecycle import RunState

app = typer.Typer(help="Pipeline run management commands.")
console = Console()


@app.command("submit")
def submit_cmd(
    spec_path: Path = typer.Argument(..., help="Path to pipeline YAML spec"),
    watch: bool = typer.Option(
        False, "--watch", "-w", help="Watch run execution until completion"
    ),
) -> None:
    """Submit a DAG pipeline definition file."""
    try:
        submission = parse_run_spec_from_file(spec_path)
    except Exception as e:
        console.print(f"[bold red]Error parsing pipeline spec:[/] {e}")
        raise typer.Exit(code=1) from e

    async def _run() -> None:
        session = get_default_session()
        await session.start()
        client = LocalClientAdapter(session=session)

        report = await client.submit_run(submission)
        console.print(
            f"[bold green]✓[/] Run '[bold cyan]{report.run_id}[/]' submitted ({report.total_jobs} jobs)"
        )

        if watch:
            with console.status(f"[bold blue]Executing run {report.run_id}...[/]"):
                while report.state != RunState.DONE:
                    await asyncio.sleep(0.1)
                    report = await client.get_run_status(report.run_id)

            outcome_str = (
                f"[bold green]{report.outcome}[/]"
                if report.outcome == "COMPLETED" or report.outcome == "SUCCEEDED"
                else f"[bold red]{report.outcome}[/]"
            )
            console.print(f"Run completed with status: {outcome_str}")

            table = Table(title=f"Run Summary: {report.run_id}")
            table.add_column("Total", justify="center")
            table.add_column("Completed", justify="center", style="green")
            table.add_column("Failed", justify="center", style="red")
            table.add_column("Pending", justify="center", style="yellow")
            table.add_row(
                str(report.total_jobs),
                str(report.completed_jobs),
                str(report.failed_jobs),
                str(report.pending_jobs),
            )
            console.print(table)

    asyncio.run(_run())


__all__ = [
    "app",
]
