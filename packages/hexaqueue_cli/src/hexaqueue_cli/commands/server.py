"""Server daemon start command.

Notes/Architectural Intent:
    Invokes run_hexaqueue_server to boot the central scheduler controller
    and API server using the configured ASGI engine (uvicorn or granian)
    and operational role (all, gateway, worker-api, analytics, custom).
"""

import typer
from rich.console import Console

from hexaqueue_server.adapters.runner import run_hexaqueue_server
from hexaqueue_server.domain.config import (
    ServerConfig,
    ServerInterfaceConfig,
    ServerRole,
)

app = typer.Typer(
    name="server",
    help="Manage Hexaqueue central scheduler and HTTP/ASGI API server",
)
console = Console()


@app.command("start")
def start_server_cmd(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Bind host address"),
    port: int = typer.Option(8000, "--port", "-p", help="Bind port number"),
    engine: str = typer.Option(
        "uvicorn",
        "--engine",
        "-e",
        help="ASGI engine: 'uvicorn' or 'granian'",
    ),
    role: str = typer.Option(
        "all",
        "--role",
        "-r",
        help="Server role: 'all', 'gateway', 'worker-api', 'analytics', 'mcp', 'custom'",
    ),
    interfaces: str | None = typer.Option(
        None,
        "--interfaces",
        help="Comma-separated interface list (e.g. 'runs,webhooks,collateral')",
    ),
    workers: int | None = typer.Option(
        None, "--workers", "-w", help="Number of worker processes"
    ),
    reload: bool = typer.Option(
        False, "--reload", help="Enable auto-reload on code changes"
    ),
) -> None:
    """Start Hexaqueue central scheduler and API server."""
    try:
        resolved_role = ServerRole(role.lower().strip())
    except ValueError:
        console.print(f"[bold red]Error:[/] Invalid server role '{role}'.")
        raise typer.Exit(code=1) from None

    if interfaces:
        enabled_list = [i.strip().lower() for i in interfaces.split(",") if i.strip()]
        iface_cfg = ServerInterfaceConfig(
            runs="runs" in enabled_list,
            jobs="jobs" in enabled_list,
            nodes="nodes" in enabled_list,
            logs="logs" in enabled_list,
            cluster="cluster" in enabled_list,
            collateral="collateral" in enabled_list,
            budget="budget" in enabled_list,
            webhooks="webhooks" in enabled_list,
            mcp="mcp" in enabled_list,
        )
        resolved_role = ServerRole.CUSTOM
    else:
        iface_cfg = ServerInterfaceConfig.for_role(resolved_role)

    cfg = ServerConfig(
        host=host,
        port=port,
        engine=engine,
        role=resolved_role,
        interfaces=iface_cfg,
        workers=workers,
        reload=reload,
    )

    console.print(
        f"[bold green]Starting Hexaqueue Server[/] (engine=[cyan]{cfg.engine}[/], "
        f"role=[cyan]{cfg.role.value}[/], port=[cyan]{cfg.port}[/])..."
    )

    try:
        run_hexaqueue_server(config=cfg, fallback_to_uvicorn=True)
    except Exception as exc:
        console.print(f"[bold red]Failed to start server:[/] {exc}")
        raise typer.Exit(code=1) from exc


__all__ = [
    "app",
]
