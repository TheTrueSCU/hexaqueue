"""CLI subcommand group for compute node management and bastion access.

Notes/Architectural Intent:
    Provides `hq node` commands to inspect worker nodes and establish
    administrative bastion terminal sessions, enforcing explicit elevation.
"""

import asyncio
import os
import subprocess

import typer
from rich.console import Console

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.adapters.presenter import CliPresenter
from hexaqueue_cli.infra.options import format_option, resolve_format

app = typer.Typer(
    name="node",
    help="Inspect worker nodes and establish administrative bastion sessions",
    no_args_is_help=True,
)
console = Console()


@app.command("list")
def list_nodes_cmd(
    format_type: str = format_option(),
) -> None:
    """List registered compute worker nodes and their telemetry pulses.

    Args:
        format_type: Chosen serialization output format.
    """
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    async def _nodes() -> None:
        client = LocalClientAdapter()
        try:
            nodes = await client.get_nodes()
            presenter.render_nodes_table(nodes, resolved_fmt)
        except Exception as exc:
            console.print(f"[bold red]Error fetching worker nodes:[/] {exc}")
            raise typer.Exit(code=1) from exc

    asyncio.run(_nodes())


@app.command("ssh")
def ssh_node_cmd(
    node_id: str = typer.Argument(
        ..., help="Target worker node ID or private IP to attach to"
    ),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Assert explicit administrative elevation for bastion shell access",
    ),
    user: str = typer.Option(
        "default",
        "--user",
        "-u",
        help="Requesting user identity",
    ),
    direct: bool = typer.Option(
        False,
        "--direct",
        help="Connect directly via SSH jump-host through controller instead of controller API session",
    ),
    jump_host: str | None = typer.Option(
        None,
        "--jump-host",
        help="Jump host public IP/hostname for direct connection",
    ),
    jump_user: str = typer.Option(
        "ubuntu",
        "--jump-user",
        help="Jump host SSH user",
    ),
) -> None:
    """Open an administrative bastion terminal session on a worker node.

    Args:
        node_id: Target compute node worker ID or private IP.
        admin: Explicit administrative elevation confirmation.
        user: Requesting user identity.
        direct: Whether to connect directly via SSH jump host.
        jump_host: Public IP/hostname of jump host.
        jump_user: Administrative user on jump host.

    Notes/Architectural Intent:
        Enforces least privilege: connecting to worker node underlying infrastructure
        requires explicit administrative elevation (--admin). Direct mode allows
        out-of-band rescue when the in-band controller API is unreachable.
    """
    if not admin:
        console.print(
            f"[bold red]Permission denied:[/] Bastion shell access on node '{node_id}' "
            "requires explicit administrative elevation (--admin)."
        )
        raise typer.Exit(code=1)

    if direct:
        target_jump_host = jump_host or os.environ.get(
            "HEXAQUEUE_CLUSTER_HOST", "129.146.115.79"
        )
        target_jump_user = jump_user or os.environ.get("HEXAQUEUE_ADMIN_USER", "ubuntu")
        target = f"ubuntu@{node_id}"

        ssh_cmd = [
            "ssh",
            "-A",
            "-t",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-J",
            f"{target_jump_user}@{target_jump_host}",
            target,
        ]
        console.print(
            f"[dim]Connecting to {target} via jump host {target_jump_user}@{target_jump_host}...[/]"
        )
        try:
            proc = subprocess.run(ssh_cmd, check=False)
            if proc.returncode != 0:
                raise typer.Exit(code=proc.returncode)
            return
        except KeyboardInterrupt:
            raise typer.Exit(code=130) from None

    async def _ssh() -> None:
        client = LocalClientAdapter()
        try:
            session = await client.create_bastion_session(
                node_id=node_id, user_id=user, elevate=admin
            )
            console.print(
                f"[bold green]✓[/] Bastion terminal session '[bold cyan]{session.session_id}[/]' established on node '{node_id}'."
            )
        except Exception as exc:
            console.print(f"[bold red]Error opening bastion terminal:[/] {exc}")
            raise typer.Exit(code=1) from exc

    asyncio.run(_ssh())


__all__ = [
    "app",
]
