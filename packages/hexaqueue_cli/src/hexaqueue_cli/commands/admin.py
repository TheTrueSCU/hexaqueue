"""CLI subcommand group for administrative operations and bastion session governance.

Notes/Architectural Intent:
    Provides `hq admin session` commands to mint zero-trust bastion sessions,
    generate cloud-specific tunnel connection commands, audit active sessions,
    and terminate maintenance leases across AWS SSM, GCP IAP, Azure Bastion,
    Tailscale/Teleport, and Native Break-Glass setups.
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.panel import Panel

from hexaqueue_cli.adapters.presenter import CliPresenter
from hexaqueue_cli.infra.options import format_option, resolve_format
from hexaqueue_core.adapters.bastion import (
    AWSSSMAdapter,
    AzureBastionAdapter,
    GCPIAPAdapter,
    NativeBreakGlassAdapter,
    TailscaleTeleportAdapter,
)
from hexaqueue_core.domain.bastion import BastionProtocolType
from hexaqueue_core.ports.bastion import BastionAccessPort

app = typer.Typer(
    name="admin",
    help="Administrative operations and zero-trust session governance",
    no_args_is_help=True,
)
session_app = typer.Typer(
    name="session",
    help="Manage and audit zero-trust bastion operator access sessions",
    no_args_is_help=True,
)
app.add_typer(session_app, name="session")
console = Console()


def get_bastion_adapter(protocol: BastionProtocolType) -> BastionAccessPort:
    """Resolve the appropriate bastion adapter for a given protocol."""
    if protocol == BastionProtocolType.AWS_SSM:
        return AWSSSMAdapter()
    if protocol == BastionProtocolType.GCP_IAP:
        return GCPIAPAdapter()
    if protocol == BastionProtocolType.AZURE_BASTION:
        return AzureBastionAdapter()
    if protocol == BastionProtocolType.TAILSCALE_TELEPORT:
        return TailscaleTeleportAdapter()
    return NativeBreakGlassAdapter()


@session_app.command("create")
def create_session_cmd(
    node_id: str = typer.Argument(..., help="Target compute node ID"),
    operator: str = typer.Option(
        "default", "--operator", "-o", help="Requesting operator identity"
    ),
    protocol: BastionProtocolType = typer.Option(
        BastionProtocolType.NATIVE_BREAK_GLASS,
        "--protocol",
        "-p",
        help="Bastion access protocol",
    ),
    duration: int = typer.Option(
        3600, "--duration", "-d", help="Lease duration in seconds"
    ),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Assert explicit administrative elevation for bastion shell access",
    ),
) -> None:
    """Mint an ephemeral zero-trust bastion session and generate connection command."""
    if not admin:
        console.print(
            f"[bold red]Permission denied:[/] Minting bastion session on node '{node_id}' "
            "requires explicit administrative elevation (--admin)."
        )
        raise typer.Exit(code=1)

    adapter = get_bastion_adapter(protocol)

    async def _create() -> None:
        try:
            session = await adapter.generate_session_token(
                node_id=node_id,
                operator_id=operator,
                duration_seconds=duration,
            )
            cmd = await adapter.get_connection_command(node_id, session)

            console.print(
                f"[bold green]✓[/] Bastion session '[bold cyan]{session.session_id}[/]' "
                f"minted for operator '[bold yellow]{operator}[/]'.\n"
                f"    Protocol: [magenta]{session.protocol.value}[/]\n"
                f"    Expires:  [dim]{session.expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')}[/]"
            )
            console.print(
                Panel(
                    cmd.as_shell_string(),
                    title="[bold green]Connection Command[/]",
                    border_style="green",
                )
            )
        except Exception as exc:
            console.print(f"[bold red]Error creating bastion session:[/] {exc}")
            raise typer.Exit(code=1) from exc

    asyncio.run(_create())


@session_app.command("list")
def list_sessions_cmd(
    protocol: BastionProtocolType = typer.Option(
        BastionProtocolType.NATIVE_BREAK_GLASS,
        "--protocol",
        "-p",
        help="Target bastion access protocol to audit",
    ),
    format_type: str = format_option(),
) -> None:
    """Audit and list active unexpired bastion sessions."""
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)
    adapter = get_bastion_adapter(protocol)

    async def _list() -> None:
        try:
            sessions = await adapter.audit_active_sessions()
            presenter.render_bastion_sessions_table(sessions, resolved_fmt)
        except Exception as exc:
            console.print(f"[bold red]Error auditing bastion sessions:[/] {exc}")
            raise typer.Exit(code=1) from exc

    asyncio.run(_list())


@session_app.command("terminate")
def terminate_session_cmd(
    session_id: str = typer.Argument(..., help="Target session ID to terminate"),
    protocol: BastionProtocolType = typer.Option(
        BastionProtocolType.NATIVE_BREAK_GLASS,
        "--protocol",
        "-p",
        help="Bastion access protocol governing the session",
    ),
) -> None:
    """Revoke an active bastion session immediately."""
    adapter = get_bastion_adapter(protocol)

    async def _terminate() -> None:
        try:
            await adapter.terminate_session(session_id)
            console.print(
                f"[bold green]✓[/] Bastion session '[bold cyan]{session_id}[/]' successfully terminated."
            )
        except Exception as exc:
            console.print(f"[bold red]Error terminating bastion session:[/] {exc}")
            raise typer.Exit(code=1) from exc

    asyncio.run(_terminate())


__all__ = [
    "app",
    "get_bastion_adapter",
]
