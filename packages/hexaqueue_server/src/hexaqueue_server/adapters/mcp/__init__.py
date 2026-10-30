"""Model Context Protocol (MCP) server driving adapters for Hexaqueue.

Notes/Architectural Intent:
    Exposes Hexaqueue's central CQRS command and query execution pipeline as
    Model Context Protocol (MCP) tools over stdio and Server-Sent Events (SSE).
"""

from hexaqueue_server.adapters.mcp.server import (
    create_mcp_server,
    mount_mcp_server,
    run_mcp_stdio,
    run_mcp_stdio_async,
)

__all__ = [
    "create_mcp_server",
    "mount_mcp_server",
    "run_mcp_stdio",
    "run_mcp_stdio_async",
]
