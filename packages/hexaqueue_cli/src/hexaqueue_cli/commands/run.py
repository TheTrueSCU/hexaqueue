"""CLI commands for run submission and lifecycle management.

Notes/Architectural Intent:
    Provides subcommands for submitting YAML DAG specs, inspecting status,
    and canceling active runs with Rich terminal tables.
"""

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.adapters.presenter import CliPresenter
from hexaqueue_cli.domain.parser import parse_run_spec_from_file
from hexaqueue_cli.domain.session import get_default_session
from hexaqueue_cli.infra.options import format_option, resolve_format
from hexaqueue_core.domain.lifecycle import RunState

app = typer.Typer(help="Pipeline run management commands.")
console = Console()


@app.command("submit")
def submit_cmd(
    spec_path: Path = typer.Argument(..., help="Path to pipeline YAML spec"),
    watch: bool = typer.Option(
        False, "--watch", "-w", help="Watch run execution until completion"
    ),
    format_type: str = format_option(),
) -> None:
    """Submit a DAG pipeline definition file."""
    try:
        submission = parse_run_spec_from_file(spec_path)
    except Exception as e:
        console.print(f"[bold red]Error parsing pipeline spec:[/] {e}")
        raise typer.Exit(code=1) from e

    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _run() -> None:
        session = get_default_session()
        await session.start()
        client = LocalClientAdapter(session=session)

        report = await client.submit_run(submission)
        if resolved_fmt in ("table", "rich"):
            console.print(
                f"[bold green]✓[/] Run '[bold cyan]{report.run_id}[/]' submitted ({report.total_jobs} jobs)"
            )
        else:
            presenter.render_run_status(report, resolved_fmt)

        if not watch:
            return

        with console.status(f"[bold blue]Executing run {report.run_id}...[/]"):
            while report.state not in (RunState.DONE, RunState.BLOCKED):
                await asyncio.sleep(0.1)
                report = await client.get_run_status(report.run_id)

        if resolved_fmt in ("table", "rich"):
            outcome_str = (
                f"[bold green]{report.outcome}[/]"
                if str(report.outcome) in ("COMPLETED", "SUCCEEDED")
                else f"[bold red]{report.outcome}[/]"
            )
            console.print(f"Run completed with status: {outcome_str}")
        presenter.render_run_status(report, resolved_fmt)

    asyncio.run(_run())


__all__ = [
    "app",
]
