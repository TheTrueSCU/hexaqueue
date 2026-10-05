"""CLI subcommand group for compute node management and bastion access.

Notes/Architectural Intent:
    Provides `hq node` commands to inspect worker nodes and establish
    administrative bastion terminal sessions, enforcing explicit elevation.
"""

import asyncio

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
    node_id: str = typer.Argument(..., help="Target worker node ID to attach to"),
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
) -> None:
    """Open an administrative bastion terminal session on a worker node.

    Args:
        node_id: Target compute node worker ID.
        admin: Explicit administrative elevation confirmation.
        user: Requesting user identity.

    Notes/Architectural Intent:
        Enforces least privilege: connecting to worker node underlying infrastructure
        requires explicit administrative elevation (--admin).
    """
    if not admin:
        console.print(
            f"[bold red]Permission denied:[/] Bastion shell access on node '{node_id}' "
            "requires explicit administrative elevation (--admin)."
        )
        raise typer.Exit(code=1)

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
