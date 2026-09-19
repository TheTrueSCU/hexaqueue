"""Main CLI entrypoint for hexaqueue (hq).

Notes/Architectural Intent:
    Root Typer application dispatching subcommands and top-level helpers
    (status, list, logs, cancel, hold, release, stat, top, nodes, quota, exec, attach).
"""

import asyncio
from uuid import uuid4

import typer
from rich.console import Console

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.adapters.presenter import CliPresenter
from hexaqueue_cli.commands.run import app as run_app
from hexaqueue_cli.commands.workflow import app as workflow_app
from hexaqueue_cli.infra.options import format_option, resolve_format
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_worker.domain.pty import PtySessionRequest

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
    """Check status of a run or job.

    Args:
        target_id: Identifier of the run or job to inspect.
        format_type: Chosen serialization output format.

    Notes/Architectural Intent:
        Attempts run status resolution first, falling back to individual job inspection.
    """
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


def _print_log_chunk(chunk: LogChunk) -> None:
    """Format and print an individual log chunk to the terminal."""
    if chunk.stream == "stderr":
        console.print(f"[bold red][stderr][/] {chunk.content}", end="")
    elif chunk.stream == "system":
        console.print(f"[cyan][system][/] {chunk.content}", end="")
    else:
        console.print(chunk.content, end="")


async def _stream_live_logs(
    client: LocalClientAdapter, job_id: str, tail: int | None
) -> None:
    """Stream live logs until cancelled."""
    try:
        async for chunk in client.stream_logs(job_id, follow=True, tail=tail):
            _print_log_chunk(chunk)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass


@app.command("logs")
def logs_cmd(
    job_id: str = typer.Argument(..., help="Job ID to fetch logs for"),
    follow: bool = typer.Option(
        False, "--follow", "-f", help="Follow stream output in real time"
    ),
    tail: int | None = typer.Option(
        None, "--tail", "-n", help="Number of lines to show from end"
    ),
) -> None:
    """View stdout and stderr logs for a job.

    Args:
        job_id: Target job identifier.
        follow: Stream chunks asynchronously in real time.
        tail: Number of historical lines to tail.

    Notes/Architectural Intent:
        Demuxes real-time stdout, stderr, and system log chunks with ANSI fidelity.
    """

    async def _logs() -> None:
        client = LocalClientAdapter()
        if follow:
            await _stream_live_logs(client, job_id, tail)
            return

        logs = await client.get_logs(job_id)
        if not logs:
            console.print(f"[dim]No logs recorded for job '{job_id}'[/]")
            return
        selected = logs[-tail:] if tail is not None and tail > 0 else logs
        for chunk in selected:
            _print_log_chunk(chunk)

    asyncio.run(_logs())


@app.command("cancel")
def cancel_cmd(
    target_id: str = typer.Argument(..., help="Run ID or Job ID to cancel"),
) -> None:
    """Cancel an active pipeline run or individual job.

    Args:
        target_id: Identifier of the run or job to cancel.

    Notes/Architectural Intent:
        Attempts run cancellation first, falling back to individual job cancellation.
    """

    async def _cancel() -> None:
        client = LocalClientAdapter()
        try:
            report = await client.cancel_run(target_id)
            console.print(f"[bold yellow]✓[/] Run '{report.run_id}' cancelled.")
            return
        except Exception:
            pass

        try:
            job = await client.cancel_job(target_id)
            console.print(f"[bold yellow]✓[/] Job '{job.id}' cancelled.")
        except Exception as e:
            console.print(f"[bold red]Error cancelling '{target_id}':[/] {e}")
            raise typer.Exit(code=1) from e

    asyncio.run(_cancel())


@app.command("hold")
def hold_cmd(
    job_id: str = typer.Argument(..., help="Job ID to place on administrative hold"),
) -> None:
    """Place an administrative hold on a pending job.

    Args:
        job_id: Identifier of the pending job to hold.

    Notes/Architectural Intent:
        Transitions job state to BLOCKED and removes it from the scheduling candidate pool.
    """

    async def _hold() -> None:
        client = LocalClientAdapter()
        try:
            job = await client.hold_job(job_id)
            console.print(
                f"[bold yellow]⏸[/] Job '{job.id}' placed on administrative hold."
            )
        except Exception as e:
            console.print(f"[bold red]Error placing hold on job '{job_id}':[/] {e}")
            raise typer.Exit(code=1) from e

    asyncio.run(_hold())


@app.command("release")
def release_cmd(
    job_id: str = typer.Argument(
        ..., help="Job ID to release from administrative hold"
    ),
) -> None:
    """Release an administrative hold on a job back to the queue.

    Args:
        job_id: Identifier of the blocked job to release.

    Notes/Architectural Intent:
        Transitions job back to PENDING and re-enqueues into the priority scheduler queue.
    """

    async def _release() -> None:
        client = LocalClientAdapter()
        try:
            job = await client.release_job(job_id)
            console.print(f"[bold green]▶[/] Job '{job.id}' released from hold.")
        except Exception as e:
            console.print(f"[bold red]Error releasing job '{job_id}':[/] {e}")
            raise typer.Exit(code=1) from e

    asyncio.run(_release())


@app.command("stat")
def stat_cmd(
    format_type: str = format_option(),
) -> None:
    """Display high-level cluster state and backlog statistics.

    Args:
        format_type: Output format (table, json, markdown, plain, rich).

    Notes/Architectural Intent:
        Provides rapid cluster health and queue backlog telemetry.
    """
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _stat() -> None:
        client = LocalClientAdapter()
        try:
            stats = await client.get_cluster_stats()
            presenter.render_cluster_stats(stats, resolved_fmt)
        except Exception as e:
            console.print(f"[bold red]Error retrieving cluster stats:[/] {e}")
            raise typer.Exit(code=1) from e

    asyncio.run(_stat())


@app.command("nodes")
def nodes_cmd(
    format_type: str = format_option(),
) -> None:
    """Display compute worker nodes telemetry and accelerator status.

    Args:
        format_type: Output format (table, json, markdown, plain, rich).

    Notes/Architectural Intent:
        Surfaces real-time hardware telemetry per worker compute node.
    """
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _nodes() -> None:
        client = LocalClientAdapter()
        try:
            nodes = await client.get_nodes()
            presenter.render_nodes_table(nodes, resolved_fmt)
        except Exception as e:
            console.print(f"[bold red]Error retrieving compute nodes:[/] {e}")
            raise typer.Exit(code=1) from e

    asyncio.run(_nodes())


@app.command("quota")
def quota_cmd(
    format_type: str = format_option(),
) -> None:
    """Inspect hierarchical fair-share tree, historical usage, and quota allowances.

    Args:
        format_type: Output format (table, json, markdown, plain, rich).

    Notes/Architectural Intent:
        Exposes fair-share tree and quota consumption under active multi-tenant hierarchy.
    """
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _quota() -> None:
        client = LocalClientAdapter()
        try:
            report = await client.get_fairshare_tree()
            presenter.render_fairshare_tree(report, resolved_fmt)
        except Exception as e:
            console.print(f"[bold red]Error querying quota allowances:[/] {e}")
            raise typer.Exit(code=1) from e

    asyncio.run(_quota())


@app.command("top")
def top_cmd(
    interval: float = typer.Option(
        1.0, "--interval", "-i", help="Refresh interval in seconds"
    ),
    once: bool = typer.Option(
        False, "--once", "-1", help="Print dashboard once and exit"
    ),
) -> None:
    """Interactive live cluster and queue monitoring dashboard.

    Args:
        interval: Refresh period in seconds for live loop.
        once: Print static dashboard snapshot and exit immediately.

    Notes/Architectural Intent:
        Composes cluster summary, node telemetry, and top running/queued jobs into a reactive view.
    """
    presenter = CliPresenter(console=console)

    async def _top() -> None:
        client = LocalClientAdapter()
        if once:
            stats = await client.get_cluster_stats()
            nodes = await client.get_nodes()
            jobs = await client.list_jobs()
            presenter.render_top_dashboard(stats, nodes, jobs)
            return

        from rich.live import Live

        stats = await client.get_cluster_stats()
        nodes = await client.get_nodes()
        jobs = await client.list_jobs()
        dashboard = presenter.build_top_dashboard(stats, nodes, jobs)

        refresh_rate = max(1, int(1.0 / max(interval, 0.1)))
        try:
            with Live(
                dashboard, console=console, refresh_per_second=refresh_rate
            ) as live:
                while True:
                    await asyncio.sleep(interval)
                    stats = await client.get_cluster_stats()
                    nodes = await client.get_nodes()
                    jobs = await client.list_jobs()
                    live.update(presenter.build_top_dashboard(stats, nodes, jobs))
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass

    asyncio.run(_top())


@app.command("exec")
def exec_cmd(
    job_id: str = typer.Argument(..., help="Job ID to execute command in"),
    command: list[str] = typer.Argument(
        ..., help="Command vector to run inside job environment"
    ),
    user: str = typer.Option("default", "--user", "-u", help="Requesting username"),
) -> None:
    """Spawn an interactive PTY session inside a running job environment.

    Args:
        job_id: Target running job identifier.
        command: Command vector to execute in terminal PTY.
        user: Requesting user identity for RBAC validation.

    Notes/Architectural Intent:
        Connects local terminal to remote worker PTY master bridge with RBAC authorization.
    """

    async def _exec() -> None:
        client = LocalClientAdapter()
        request = PtySessionRequest(
            session_id=f"pty-{uuid4().hex[:8]}",
            job_id=job_id,
            user_id=user,
            roles=["operator"],
            command=command,
        )
        try:
            session_info = await client.create_pty_session(request, job_owner=user)
            console.print(
                f"[bold green]✓[/] Attached PTY session '{session_info.session_id}' "
                f"to job '{job_id}' (pid: {session_info.pid})"
            )
        except Exception as e:
            console.print(
                f"[bold red]Error launching PTY session for '{job_id}':[/] {e}"
            )
            raise typer.Exit(code=1) from e

    asyncio.run(_exec())


@app.command("attach")
def attach_cmd(
    job_id: str = typer.Argument(..., help="Job ID to attach interactive shell to"),
    user: str = typer.Option("default", "--user", "-u", help="Requesting username"),
) -> None:
    """Attach an interactive bash shell to a running job.

    Args:
        job_id: Target running job identifier.
        user: Requesting user identity for RBAC validation.

    Notes/Architectural Intent:
        Convenience alias launching an interactive bash terminal inside the target job.
    """

    async def _attach() -> None:
        client = LocalClientAdapter()
        request = PtySessionRequest(
            session_id=f"pty-{uuid4().hex[:8]}",
            job_id=job_id,
            user_id=user,
            roles=["operator"],
            command=["/bin/bash"],
        )
        try:
            session_info = await client.create_pty_session(request, job_owner=user)
            console.print(
                f"[bold green]✓[/] Attached shell session '{session_info.session_id}' "
                f"to job '{job_id}' (pid: {session_info.pid})"
            )
        except Exception as e:
            console.print(f"[bold red]Error attaching to job '{job_id}':[/] {e}")
            raise typer.Exit(code=1) from e

    asyncio.run(_attach())


@app.command("why")
def why_cmd(
    job_id: str = typer.Argument(..., help="Job ID to explain"),
) -> None:
    """Explain why a job is currently waiting in the queue."""
    presenter = CliPresenter(console=console)

    async def _why() -> None:
        client = LocalClientAdapter()
        try:
            report = await client.explain_job(job_id)
            presenter.render_why_summary(report)
        except Exception as e:
            console.print(
                f"[bold red]Error querying explanation for '{job_id}':[/] {e}"
            )
            raise typer.Exit(code=1) from e

    asyncio.run(_why())


@app.command("explain")
def explain_cmd(
    job_id: str = typer.Argument(..., help="Job ID to explain"),
    format_type: str = format_option(),
) -> None:
    """Display rich priority math and resource blocker breakdown for a job."""
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _explain() -> None:
        client = LocalClientAdapter()
        try:
            report = await client.explain_job(job_id)
            presenter.render_explain_report(report, resolved_fmt)
        except Exception as e:
            console.print(f"[bold red]Error explaining job '{job_id}':[/] {e}")
            raise typer.Exit(code=1) from e

    asyncio.run(_explain())


@app.command("fairshare")
def fairshare_cmd(
    format_type: str = format_option(),
) -> None:
    """Inspect hierarchical fair-share tree, historical usage, and decay factors."""
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _fairshare() -> None:
        client = LocalClientAdapter()
        try:
            report = await client.get_fairshare_tree()
            presenter.render_fairshare_tree(report, resolved_fmt)
        except Exception as e:
            console.print(f"[bold red]Error querying fair-share tree:[/] {e}")
            raise typer.Exit(code=1) from e

    asyncio.run(_fairshare())


__all__ = [
    "app",
]
