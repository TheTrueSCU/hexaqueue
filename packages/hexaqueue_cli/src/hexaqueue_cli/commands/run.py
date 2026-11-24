"""CLI commands for run submission and lifecycle management.

Notes/Architectural Intent:
    Provides subcommands for submitting YAML DAG specs, listing active runs,
    inspecting status, and canceling runs with Rich terminal tables across both
    in-process local sessions and remote ``hexaqueue-server`` controllers.
"""

import asyncio
from pathlib import Path

import typer
from rich.console import Console

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.adapters.presenter import CliPresenter
from hexaqueue_cli.domain.parser import parse_run_spec_from_file
from hexaqueue_cli.domain.session import (
    LocalCliSession,
    get_default_session,
    resolve_controller_url,
)
from hexaqueue_cli.infra.options import format_option, resolve_format, url_option
from hexaqueue_core.domain.config import ExecutionMode
from hexaqueue_core.domain.lifecycle import RunState
from hexaqueue_core.domain.notification import (
    NotificationPolicy,
    NotificationTrigger,
)
from hexaqueue_core.infra.notification import NotificationDispatcher
from hexaqueue_server.domain.models import RunSubmission

app = typer.Typer(help="Pipeline run management commands.")
console = Console()


def _create_apprise_dispatcher() -> NotificationDispatcher | None:
    try:
        from hexastack_events.adapters.notifications.apprise import (
            AppriseNotificationAdapter,
        )

        return NotificationDispatcher(notification_port=AppriseNotificationAdapter())
    except Exception:
        return None


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
    has_notifications: bool = False,
    *,
    user_id: str = "default",
    elevate: bool = False,
    controller_url: str | None = None,
) -> None:
    """Execute submission and optional status polling."""
    resolved_url = resolve_controller_url(controller_url)
    session: LocalCliSession | None = None
    started_session = False
    if resolved_url is not None:
        client = LocalClientAdapter(controller_url=resolved_url)
    else:
        session_mode = ExecutionMode.FREE_TIER if free_tier else None
        dispatcher = _create_apprise_dispatcher() if has_notifications else None
        session = get_default_session(
            mode=session_mode, notification_dispatcher=dispatcher
        )
        client = LocalClientAdapter(session=session)
        if watch:
            await session.start()
            started_session = True

    try:
        report = await client.submit_run(submission, user_id=user_id, elevate=elevate)
        if resolved_fmt in ("table", "rich"):
            console.print(
                f"[bold green]✓[/] Run '[bold cyan]{report.run_id}[/]' submitted ({report.total_jobs} jobs)"
            )
        else:
            presenter.render_run_status(report, resolved_fmt)

        if not watch:
            if resolved_url is None and resolved_fmt in ("table", "rich"):
                console.print(
                    "[bold yellow]Notice:[/] Local session submitted in detached mode. "
                    "In-process execution will terminate when the process exits. Use --watch to await completion."
                )
            return

        with console.status(f"[bold blue]Executing run {report.run_id}...[/]"):
            while report.state not in (RunState.DONE, RunState.BLOCKED):
                await asyncio.sleep(0.1)
                report = await client.get_run_status(
                    report.run_id, user_id=user_id, elevate=elevate
                )

        if resolved_fmt in ("table", "rich"):
            outcome_str = (
                f"[bold green]{report.outcome}[/]"
                if str(report.outcome) in ("COMPLETED", "SUCCEEDED")
                else f"[bold red]{report.outcome}[/]"
            )
            console.print(f"Run completed with status: {outcome_str}")
        presenter.render_run_status(report, resolved_fmt)
    finally:
        if started_session and session is not None:
            await session.stop()


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
    user: str = typer.Option(
        "default", "--user", "-u", help="Submitting user identity"
    ),
    admin: bool = typer.Option(
        False, "--admin", help="Assert explicit administrative elevation"
    ),
    url: str | None = url_option(),
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
            has_notifications=bool(notify),
            user_id=user,
            elevate=admin,
            controller_url=url,
        )
    )


@app.command("list")
def list_runs_cmd(
    limit: int = typer.Option(100, "--limit", "-l", min=1, max=1000, help="Max runs"),
    user: str = typer.Option(
        "default", "--user", "-u", help="Requesting user identity"
    ),
    admin: bool = typer.Option(
        False, "--admin", help="Assert explicit administrative elevation"
    ),
    format_type: str = format_option(),
    url: str | None = url_option(),
) -> None:
    """List pipeline runs visible to the caller.

    Args:
        limit: Maximum number of runs to return.
        user: Requesting user identity.
        admin: Administrative elevation flag.
        format_type: Output presentation format.
        url: Optional remote controller base URL.
    """
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _list() -> None:
        client = LocalClientAdapter(controller_url=url)
        try:
            runs = await client.list_runs(limit=limit, user_id=user, elevate=admin)
            presenter.render_runs_table(runs, resolved_fmt)
        except Exception as e:
            console.print(f"[bold red]Error listing runs:[/] {e}")
            raise typer.Exit(code=1) from e

    asyncio.run(_list())


@app.command("cancel")
def cancel_run_cmd(
    run_id: str = typer.Argument(..., help="Run ID to cancel"),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Assert explicit administrative elevation for cross-user cancellation",
    ),
    user: str = typer.Option(
        "default",
        "--user",
        "-u",
        help="Requesting user identity",
    ),
    url: str | None = url_option(),
) -> None:
    """Cancel an active pipeline run.

    Args:
        run_id: Pipeline run identifier.
        admin: Explicit administrative elevation.
        user: Requesting user identity.
        url: Optional remote controller base URL.

    Notes/Architectural Intent:
        Enforces least privilege: administrative cancellation of runs submitted by other
        users requires explicit positive elevation (--admin).
    """

    async def _cancel() -> None:
        client = LocalClientAdapter(controller_url=url)
        try:
            report = await client.cancel_run(run_id, user_id=user, elevate=admin)
            console.print(f"[bold yellow]✓[/] Run '{report.run_id}' cancelled.")
        except Exception as e:
            console.print(f"[bold red]Error cancelling run '{run_id}':[/] {e}")
            raise typer.Exit(code=1) from e

    asyncio.run(_cancel())


__all__ = [
    "app",
]
