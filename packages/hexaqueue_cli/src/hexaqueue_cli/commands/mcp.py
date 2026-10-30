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
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline

app = typer.Typer(
    name="mcp",
    help="Manage and run Hexaqueue Model Context Protocol (MCP) server",
)
console = Console()


@app.command("run")
def run_mcp_cmd(
    name: str = typer.Option("hexaqueue-mcp", "--name", "-n", help="MCP server name"),
) -> None:
    """Run Hexaqueue MCP driving adapter over stdio transport.

    Notes/Architectural Intent:
        Standard entrypoint for AI coding assistants configured with local
        subprocesses ('hq mcp run').

    Args:
        name: Name of the MCP server instance.
    """
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    pipeline = create_hexaqueue_execution_pipeline(controller)
    run_mcp_stdio(pipeline, name=name)
