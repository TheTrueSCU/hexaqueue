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


def _build_server_config(
    config_file: str | None,
    host: str,
    port: int,
    engine: str,
    role: str,
    interfaces: str | None,
    mcp: bool | None,
    workers: int | None,
    reload: bool,
) -> ServerConfig:
    """Resolve and build validated ServerConfig combining file, role, CLI, and env settings.

    Args:
        config_file: Path to TOML configuration file if provided.
        host: Listen host string.
        port: Listen port number.
        engine: ASGI server engine name.
        role: Operational role preset string.
        interfaces: Comma-separated list of active interfaces.
        mcp: Explicit boolean toggle for MCP driving adapter.
        workers: Worker concurrency count.
        reload: Auto-reload boolean.

    Returns:
        Configured and validated ServerConfig instance.
    """
    if config_file:
        base_cfg = ServerConfig.load_from_toml(config_file, apply_env=False)
    else:
        base_cfg = ServerConfig()

    resolved_role = (
        ServerRole(role.lower().strip())
        if (role != "all" or not config_file)
        else base_cfg.role
    )

    if interfaces:
        enabled_list = [i.strip().lower() for i in interfaces.split(",") if i.strip()]
        iface_cfg = ServerInterfaceConfig(
            budget="budget" in enabled_list,
            cluster="cluster" in enabled_list,
            collateral="collateral" in enabled_list,
            jobs="jobs" in enabled_list,
            logs="logs" in enabled_list,
            mcp="mcp" in enabled_list,
            nodes="nodes" in enabled_list,
            runs="runs" in enabled_list,
            webhooks="webhooks" in enabled_list,
        )
        resolved_role = ServerRole.CUSTOM
    elif config_file and role == "all":
        iface_cfg = base_cfg.interfaces
    else:
        iface_cfg = ServerInterfaceConfig.for_role(resolved_role)

    if mcp is not None:
        iface_cfg = iface_cfg.model_copy(update={"mcp": mcp})
        mcp_cfg = base_cfg.mcp.model_copy(update={"enabled": mcp})
    else:
        mcp_cfg = base_cfg.mcp

    iface_cfg = iface_cfg.apply_feature_flags()
    mcp_cfg = mcp_cfg.apply_feature_flags()

    eff_host = host if (host != "0.0.0.0" or not config_file) else base_cfg.host
    eff_port = port if (port != 8000 or not config_file) else base_cfg.port
    eff_engine = engine if (engine != "uvicorn" or not config_file) else base_cfg.engine

    return ServerConfig(
        host=eff_host,
        port=eff_port,
        engine=eff_engine,
        role=resolved_role,
        interfaces=iface_cfg,
        mcp=mcp_cfg,
        workers=workers if workers is not None else base_cfg.workers,
        reload=reload or base_cfg.reload,
    )


@app.command("start")
def start_server_cmd(
    config_file: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to TOML configuration file (e.g. hexaqueue.toml)",
    ),
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
        help="Comma-separated interface list (e.g. 'runs,webhooks,collateral,mcp')",
    ),
    mcp: bool | None = typer.Option(
        None,
        "--mcp/--no-mcp",
        help="Explicitly enable or disable MCP driving adapter",
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
        cfg = _build_server_config(
            config_file=config_file,
            host=host,
            port=port,
            engine=engine,
            role=role,
            interfaces=interfaces,
            mcp=mcp,
            workers=workers,
            reload=reload,
        )
    except ValueError:
        console.print(f"[bold red]Error:[/] Invalid server role '{role}'.")
        raise typer.Exit(code=1) from None
    except Exception as exc:
        console.print(f"[bold red]Configuration error:[/] {exc}")
        raise typer.Exit(code=1) from exc

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
