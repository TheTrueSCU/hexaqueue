"""Unit tests for Hexaqueue MCP driving adapter and tool execution."""

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.adapters.mcp.server import (
    create_mcp_server,
    mount_mcp_server,
    run_mcp_stdio,
    run_mcp_stdio_async,
)
from hexaqueue_server.domain.config import McpConfig, McpToolConfig
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline


def _extract_tool_result(res: Any) -> Any:
    """Helper to extract structured tool result across FastMCP response formats.

    Args:
        res: Raw FastMCP call_tool return value.

    Returns:
        Extracted python object.
    """
    if isinstance(res, tuple):
        _contents, structured = res
        if (
            isinstance(structured, dict)
            and "result" in structured
            and len(structured) == 1
        ):
            return structured["result"]
        return structured
    if isinstance(res, list) and res and hasattr(res[0], "text"):
        return json.loads(res[0].text)
    return res


@pytest.fixture
def test_pipeline() -> ExecutionPipeline:
    """Fixture providing a configured ExecutionPipeline with an in-memory queue."""
    queue = InMemoryJobQueueAdapter()
    controller = LocalSchedulerControllerAdapter(queue=queue)
    log_store: dict[str, list[LogChunk]] = {
        "job-test-1": [
            LogChunk(
                job_id="job-test-1",
                stream="stdout",
                content="Build started\n",
                offset=0,
                timestamp=datetime.now(UTC),
            ),
            LogChunk(
                job_id="job-test-1",
                stream="stderr",
                content="Warning: unused import\n",
                offset=1,
                timestamp=datetime.now(UTC),
            ),
        ]
    }
    return create_hexaqueue_execution_pipeline(controller, log_store=log_store)


@pytest.fixture
def mcp_server(test_pipeline: ExecutionPipeline) -> FastMCP:
    """Fixture providing an initialized FastMCP server."""
    return create_mcp_server(test_pipeline)


async def test_create_mcp_server_registers_all_tools(
    mcp_server: FastMCP,
) -> None:
    """Verify that create_mcp_server registers all required MCP tools."""
    tools = await mcp_server.list_tools()
    tool_names = {tool.name for tool in tools}

    expected_tools = {
        "hq_list_jobs",
        "hq_submit_run",
        "hq_get_run_status",
        "hq_lease_task",
        "hq_get_cluster_nodes",
        "hq_stream_logs",
    }
    res_intersection = expected_tools.intersection(tool_names)
    assert res_intersection == expected_tools


async def test_mcp_submit_run_and_status(mcp_server: FastMCP) -> None:
    """Verify submitting a multi-step pipeline run and querying its status."""
    run_payload = {
        "run_name": "ai-orchestrated-workflow",
        "run_id": "run-mcp-001",
        "jobs": [
            {"id": "step-prepare", "name": "prepare", "command": "echo prepare"},
            {"id": "step-crunch", "name": "crunch", "command": "echo crunch"},
        ],
        "dependencies": {"step-crunch": ["step-prepare"]},
        "user_id": "alice",
    }

    raw_result = await mcp_server.call_tool("hq_submit_run", run_payload)
    submit_report = _extract_tool_result(raw_result)
    res_run_id = submit_report.get("run_id")
    assert res_run_id == "run-mcp-001"

    raw_status = await mcp_server.call_tool(
        "hq_get_run_status", {"run_id": "run-mcp-001", "user_id": "alice"}
    )
    status_report = _extract_tool_result(raw_status)
    res_status_id = status_report.get("run_id")
    assert res_status_id == "run-mcp-001"
    res_pending_jobs = status_report.get("pending_jobs", 0)
    assert res_pending_jobs >= 1


async def test_mcp_list_jobs_and_filtering(mcp_server: FastMCP) -> None:
    """Verify listing jobs with and without status filtering."""
    run_payload = {
        "run_name": "filter-test",
        "run_id": "run-mcp-002",
        "jobs": [
            {"id": "filter-job-1", "name": "step1", "command": "echo 1"},
        ],
        "user_id": "bob",
    }
    await mcp_server.call_tool("hq_submit_run", run_payload)

    raw_all = await mcp_server.call_tool("hq_list_jobs", {"user_id": "bob"})
    all_jobs = _extract_tool_result(raw_all)
    res_all_count = len(all_jobs)
    assert res_all_count >= 1

    raw_pending = await mcp_server.call_tool(
        "hq_list_jobs", {"user_id": "bob", "status": "PENDING"}
    )
    pending_jobs = _extract_tool_result(raw_pending)
    res_pending_count = len(pending_jobs)
    assert res_pending_count >= 1

    raw_completed = await mcp_server.call_tool(
        "hq_list_jobs", {"user_id": "bob", "status": "COMPLETED"}
    )
    completed_jobs = _extract_tool_result(raw_completed)
    res_completed_count = len(completed_jobs)
    assert res_completed_count == 0


async def test_mcp_lease_task(mcp_server: FastMCP) -> None:
    """Verify leasing next available task from worker queue."""
    run_payload = {
        "run_name": "lease-test",
        "run_id": "run-mcp-003",
        "jobs": [
            {"id": "lease-job-1", "name": "target-task", "command": "echo lease"},
        ],
        "user_id": "charlie",
    }
    await mcp_server.call_tool("hq_submit_run", run_payload)

    raw_mismatch = await mcp_server.call_tool(
        "hq_lease_task",
        {
            "worker_id": "worker-gpu-01",
            "task_names": ["non-matching-task"],
            "user_id": "charlie",
        },
    )
    mismatch_lease = _extract_tool_result(raw_mismatch)
    assert mismatch_lease is None

    raw_lease = await mcp_server.call_tool(
        "hq_lease_task",
        {
            "worker_id": "worker-gpu-01",
            "task_names": ["target-task"],
            "user_id": "charlie",
        },
    )
    lease = _extract_tool_result(raw_lease)
    assert lease is not None
    res_lease_owner = lease.get("lease_owner")
    assert res_lease_owner == "worker-gpu-01"
    res_task_name = lease.get("task_name")
    assert res_task_name == "target-task"


async def test_mcp_get_cluster_nodes(mcp_server: FastMCP) -> None:
    """Verify cluster node topology and resource inspection."""
    raw_nodes = await mcp_server.call_tool(
        "hq_get_cluster_nodes", {"user_id": "admin", "elevate": True}
    )
    nodes_report = _extract_tool_result(raw_nodes)
    assert "total_nodes" in nodes_report
    res_nodes_list = isinstance(nodes_report.get("nodes"), list)
    assert res_nodes_list is True


async def test_mcp_stream_logs_and_tenant_security(
    mcp_server: FastMCP,
) -> None:
    """Verify streaming logs and enforcement of least-privilege tenant boundaries."""
    raw_logs = await mcp_server.call_tool(
        "hq_stream_logs",
        {"job_id": "job-test-1", "elevate": True},
    )
    logs = _extract_tool_result(raw_logs)
    res_chunks_count = len(logs)
    assert res_chunks_count == 2
    res_first_stream = logs[0].get("stream")
    assert res_first_stream == "stdout"

    # Verify tail parameter
    raw_tail = await mcp_server.call_tool(
        "hq_stream_logs",
        {"job_id": "job-test-1", "tail": 1, "elevate": True},
    )
    tail_logs = _extract_tool_result(raw_tail)
    res_tail_count = len(tail_logs)
    assert res_tail_count == 1
    res_tail_stream = tail_logs[0].get("stream")
    assert res_tail_stream == "stderr"

    # Verify un-elevated access for foreign job raises ToolError wrapping PermissionDeniedError
    with pytest.raises(ToolError):
        await mcp_server.call_tool(
            "hq_stream_logs",
            {"job_id": "job-test-1", "user_id": "unauthorized-user", "elevate": False},
        )


def test_mount_mcp_server(test_pipeline: ExecutionPipeline) -> None:
    """Verify mounting MCP Server SSE endpoint onto a FastAPI application."""
    app = FastAPI()
    server = mount_mcp_server(app, test_pipeline, path_prefix="/mcp")
    res_is_fastmcp = isinstance(server, FastMCP)
    assert res_is_fastmcp is True

    route_paths = [getattr(route, "path", "") for route in app.routes]
    res_mounted = any(path.startswith("/mcp") for path in route_paths)
    assert res_mounted is True


def test_run_mcp_stdio_synchronous(test_pipeline: ExecutionPipeline) -> None:
    """Verify synchronous MCP stdio runner entrypoint."""
    with patch("hexaqueue_server.adapters.mcp.server.run_stdio_server") as mock_stdio:
        run_mcp_stdio(test_pipeline)
        res_called = mock_stdio.called
        assert res_called is True


@pytest.mark.asyncio
async def test_run_mcp_stdio_asynchronous(
    test_pipeline: ExecutionPipeline,
) -> None:
    """Verify asynchronous MCP stdio runner entrypoint."""
    with patch(
        "hexaqueue_server.adapters.mcp.server.run_stdio_async", new_callable=AsyncMock
    ) as mock_stdio_async:
        await run_mcp_stdio_async(test_pipeline)
        res_called = mock_stdio_async.called
        assert res_called is True


@pytest.mark.asyncio
async def test_create_mcp_server_read_only_tool_filtering(
    test_pipeline: ExecutionPipeline,
) -> None:
    """Verify McpToolConfig.read_only disables mutation tools."""
    server = create_mcp_server(
        test_pipeline, config=McpConfig(tools=McpToolConfig.read_only())
    )
    tools = await server.list_tools()
    tool_names = {t.name for t in tools}

    assert "hq_list_jobs" in tool_names
    assert "hq_get_run_status" in tool_names
    assert "hq_get_cluster_nodes" in tool_names
    assert "hq_stream_logs" in tool_names
    assert "hq_submit_run" not in tool_names
    assert "hq_lease_task" not in tool_names


def test_mount_mcp_server_with_custom_config(
    test_pipeline: ExecutionPipeline,
) -> None:
    """Verify mount_mcp_server respects custom McpConfig path and auth."""
    app = FastAPI()
    cfg = McpConfig(path_prefix="/special-ai", sse_path="/stream")
    server = mount_mcp_server(app, test_pipeline, config=cfg)
    assert isinstance(server, FastMCP)

    route_paths = [getattr(route, "path", "") for route in app.routes]
    res_mounted = any(path.startswith("/special-ai") for path in route_paths)
    assert res_mounted is True
