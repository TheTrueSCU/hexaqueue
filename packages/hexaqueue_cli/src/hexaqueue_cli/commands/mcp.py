"""Model Context Protocol (MCP) server stdio runner command.

Notes/Architectural Intent:
    Invokes run_mcp_stdio to run Hexaqueue's central CQRS command and query bus
    over the Model Context Protocol stdio transport for direct orchestration
    by local AI coding assistants (Antigravity, Cursor, Claude Desktop).
"""

import typer
from rich.console import Console

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.adapters.mcp import run_mcp_stdio
from hexaqueue_server.domain.config import (
    McpConfig,
    McpToolConfig,
    ServerConfig,
)
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline

app = typer.Typer(
    name="mcp",
    help="Manage and run Hexaqueue Model Context Protocol (MCP) server",
)
console = Console()


def _build_mcp_config(
    config_file: str | None,
    read_only: bool,
    tools: str | None,
) -> McpConfig:
    """Build McpConfig combining configuration file, flags, and tool filters.

    Args:
        config_file: Optional path to TOML configuration file.
        read_only: Restrict tools to read-only queries.
        tools: Comma-separated list of enabled tool names.

    Returns:
        Configured McpConfig instance.
    """
    if config_file:
        server_cfg = ServerConfig.load_from_toml(config_file, apply_env=False)
        mcp_cfg = server_cfg.mcp
    else:
        mcp_cfg = McpConfig()

    if read_only:
        mcp_cfg = mcp_cfg.model_copy(
            update={
                "read_only": True,
                "tools": mcp_cfg.tools.model_copy(
                    update={"lease_task": False, "submit_run": False}
                ),
            }
        )

    if tools:
        tool_list = [t.strip().lower() for t in tools.split(",") if t.strip()]
        tool_cfg = McpToolConfig(
            get_cluster_nodes="get_cluster_nodes" in tool_list,
            get_run_status="get_run_status" in tool_list,
            lease_task="lease_task" in tool_list,
            list_jobs="list_jobs" in tool_list,
            stream_logs="stream_logs" in tool_list,
            submit_run="submit_run" in tool_list,
        )
        mcp_cfg = mcp_cfg.model_copy(update={"tools": tool_cfg})

    return mcp_cfg.apply_feature_flags()


@app.command("run")
def run_mcp_cmd(
    name: str = typer.Option("hexaqueue-mcp", "--name", "-n", help="MCP server name"),
    config_file: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to TOML configuration file",
    ),
    read_only: bool = typer.Option(
        False,
        "--read-only",
        help="Restrict MCP tools to read-only queries (disables mutations)",
    ),
    tools: str | None = typer.Option(
        None,
        "--tools",
        help="Comma-separated list of enabled tools (e.g. 'list_jobs,get_run_status')",
    ),
) -> None:
    """Run Hexaqueue MCP driving adapter over stdio transport.

    Notes/Architectural Intent:
        Standard entrypoint for AI coding assistants configured with local
        subprocesses ('hq mcp run'). Supports read-only sandboxing and granular
        tool filters via command options or TOML configuration.

    Args:
        name: Name of the MCP server instance.
        config_file: Optional path to TOML configuration file.
        read_only: Restrict MCP tools to read-only queries.
        tools: Comma-separated list of enabled tools.
    """
    try:
        mcp_cfg = _build_mcp_config(config_file, read_only, tools)
    except Exception as exc:
        console.print(f"[bold red]Configuration error:[/] {exc}")
        raise typer.Exit(code=1) from exc

    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller)
    run_mcp_stdio(pipeline, name=name, config=mcp_cfg)
