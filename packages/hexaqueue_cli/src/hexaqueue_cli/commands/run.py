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
from hexaqueue_core.domain.config import ExecutionMode
from hexaqueue_core.domain.lifecycle import RunState
from hexaqueue_core.domain.notification import (
    NotificationPolicy,
    NotificationTrigger,
)
from hexaqueue_server.domain.models import RunSubmission

app = typer.Typer(help="Pipeline run management commands.")
console = Console()


def _attach_notifications(
    submission: RunSubmission, notify: list[str], notify_on: str
) -> None:
    """Parse and attach notification policies to submission."""
    targets: list[str] = []
    for n in notify:
        targets.extend([t.strip() for t in n.split(",") if t.strip()])
    if not targets:
        return
    triggers = NotificationTrigger.parse(notify_on)
    policy = NotificationPolicy(targets=targets, triggers=triggers)
    submission.run_spec.notifications.append(policy)
    for j in submission.jobs:
        j.notifications.append(policy)


async def _execute_submit_and_watch(
    submission: RunSubmission,
    watch: bool,
    free_tier: bool,
    resolved_fmt: str,
    presenter: CliPresenter,
) -> None:
    """Execute submission and optional status polling."""
    session_mode = ExecutionMode.FREE_TIER if free_tier else None
    session = get_default_session(mode=session_mode)
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


@app.command("submit")
def submit_cmd(
    spec_path: Path = typer.Argument(..., help="Path to pipeline YAML spec"),
    watch: bool = typer.Option(
        False, "--watch", "-w", help="Watch run execution until completion"
    ),
    free_tier: bool = typer.Option(
        False,
        "--free-tier",
        help="Enable Free-Tier Safety Mode ($0.00 spend guard and strict resource clamping)",
    ),
    notify: list[str] | None = typer.Option(
        None,
        "--notify",
        "-n",
        help="Notification targets (e.g. slack://..., pagerduty://...)",
    ),
    notify_on: str = typer.Option(
        "ERRORS",
        "--notify-on",
        help="Lifecycle triggers (e.g. COMPLETED, FAILED, ERRORS, ALL)",
    ),
    format_type: str = format_option(),
) -> None:
    """Submit a DAG pipeline definition file."""
    try:
        submission = parse_run_spec_from_file(spec_path)
    except Exception as e:
        console.print(f"[bold red]Error parsing pipeline spec:[/] {e}")
        raise typer.Exit(code=1) from e

    if notify:
        _attach_notifications(submission, notify, notify_on)

    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    asyncio.run(
        _execute_submit_and_watch(
            submission=submission,
            watch=watch,
            free_tier=free_tier,
            resolved_fmt=resolved_fmt,
            presenter=presenter,
        )
    )


__all__ = [
    "app",
]
