"""Dashboard tunnel and browser launch CLI commands.

Notes/Architectural Intent:
    Provides `hq dashboard open` and `hq dashboard tunnel {start,status,stop}`
    for single-command SSH-tunneled access to the standalone dashboard UI.
"""

from __future__ import annotations

import webbrowser
from typing import Annotated

import typer
from rich.console import Console

from hexaqueue_cli.adapters.dashboard_tunnel import (
    DEFAULT_SOCKET_PATH,
    is_tunnel_active,
    start_tunnel,
    stop_tunnel,
)

app = typer.Typer(
    name="dashboard",
    help="Manage the Hexaqueue dashboard SSH tunnel and open the UI",
    no_args_is_help=True,
)
tunnel_app = typer.Typer(
    name="tunnel",
    help="Start, inspect, or stop the dashboard SSH tunnel",
    no_args_is_help=True,
)
app.add_typer(tunnel_app, name="tunnel")
console = Console()


@tunnel_app.command("start")
def tunnel_start(
    host: Annotated[str | None, typer.Option("--host", help="Remote OCI host")] = None,
    user: Annotated[
        str | None, typer.Option("--user", "-u", help="Remote SSH user")
    ] = None,
    local_port: Annotated[
        int, typer.Option("--local-port", help="Local loopback port")
    ] = 8080,
    remote_port: Annotated[
        int, typer.Option("--remote-port", help="Remote dashboard port")
    ] = 8080,
) -> None:
    """Start the SSH port-forward tunnel to the OCI dashboard if not running."""
    try:
        created = start_tunnel(
            host=host,
            user=user,
            local_port=local_port,
            remote_port=remote_port,
        )
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    url = f"http://127.0.0.1:{local_port}/dashboard/ui"
    if created:
        console.print(f"[green]Started dashboard tunnel -> {url}[/green]")
    else:
        console.print(f"[cyan]Dashboard tunnel already active -> {url}[/cyan]")


@tunnel_app.command("status")
def tunnel_status(
    host: Annotated[str | None, typer.Option("--host", help="Remote OCI host")] = None,
    user: Annotated[
        str | None, typer.Option("--user", "-u", help="Remote SSH user")
    ] = None,
    local_port: Annotated[
        int, typer.Option("--local-port", help="Local loopback port")
    ] = 8080,
) -> None:
    """Report whether the dashboard SSH tunnel is currently active."""
    active = is_tunnel_active(host=host, user=user)
    if active:
        console.print(
            f"[green]ACTIVE[/green] (socket: {DEFAULT_SOCKET_PATH}, "
            f"url: http://127.0.0.1:{local_port}/dashboard/ui)"
        )
    else:
        console.print(f"[yellow]INACTIVE[/yellow] (socket: {DEFAULT_SOCKET_PATH})")


@tunnel_app.command("stop")
def tunnel_stop(
    host: Annotated[str | None, typer.Option("--host", help="Remote OCI host")] = None,
    user: Annotated[
        str | None, typer.Option("--user", "-u", help="Remote SSH user")
    ] = None,
) -> None:
    """Destroy the active dashboard SSH tunnel."""
    stopped = stop_tunnel(host=host, user=user)
    if stopped:
        console.print("[green]Stopped dashboard SSH tunnel.[/green]")
    else:
        console.print("[yellow]No active dashboard SSH tunnel was running.[/yellow]")


@app.command("open")
def open_dashboard(
    host: Annotated[str | None, typer.Option("--host", help="Remote OCI host")] = None,
    user: Annotated[
        str | None, typer.Option("--user", "-u", help="Remote SSH user")
    ] = None,
    local_port: Annotated[
        int, typer.Option("--local-port", help="Local loopback port")
    ] = 8080,
    remote_port: Annotated[
        int, typer.Option("--remote-port", help="Remote dashboard port")
    ] = 8080,
    no_tunnel: Annotated[
        bool, typer.Option("--no-tunnel", help="Skip starting SSH tunnel")
    ] = False,
) -> None:
    """Ensure the SSH tunnel is up (if required) and open the dashboard in a browser."""
    if not no_tunnel:
        try:
            created = start_tunnel(
                host=host,
                user=user,
                local_port=local_port,
                remote_port=remote_port,
            )
            if created:
                console.print(
                    f"[green]Started dashboard tunnel on 127.0.0.1:{local_port}[/green]"
                )
        except (RuntimeError, ValueError) as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    url = f"http://127.0.0.1:{local_port}/dashboard/ui"
    webbrowser.open(url)
    console.print(f"[green]Opened {url}[/green]")


__all__ = [
    "app",
    "open_dashboard",
    "tunnel_app",
    "tunnel_start",
    "tunnel_status",
    "tunnel_stop",
]
