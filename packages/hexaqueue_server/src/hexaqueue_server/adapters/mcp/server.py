"""Model Context Protocol (MCP) server driving adapter for Hexaqueue.

Notes/Architectural Intent:
    Exposes Hexaqueue's unified CQRS command and query bus as Model Context
    Protocol (MCP) tools for modern AI coding assistants (Antigravity, Cursor,
    Claude Code). Preserves hexagonal boundaries and the Principle of Least Privilege:
    tool operations authenticate callers under natural user identity or explicit
    administrative elevation (`elevate=True`).
"""

from datetime import UTC, datetime
from typing import Any

from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_mcp.adapters.fastapi import mount_mcp_sse
from hexastack_mcp.adapters.stdio import run_stdio_async, run_stdio_server
from mcp.server.fastmcp import FastMCP

from hexaqueue_core.domain.cqrs import (
    GetLogsQuery,
    GetRunStatusQuery,
    ListComputeNodesQuery,
    ListJobsQuery,
    SubmitRunCommand,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState
from hexaqueue_server.domain.config import McpConfig
from hexaqueue_server.domain.models import TaskRecordResponse

__all__ = [
    "create_mcp_server",
    "mount_mcp_server",
    "run_mcp_stdio",
    "run_mcp_stdio_async",
]


def _serialize_result(val: Any) -> Any:
    """Recursively convert domain models or objects into JSON-compatible primitives.

    Args:
        val: Any object, collection, or Pydantic model.

    Returns:
        JSON-compatible primitive (dict, list, str, int, float, bool, None).
    """
    if hasattr(val, "model_dump"):
        return val.model_dump(mode="json")
    if isinstance(val, list):
        return [_serialize_result(item) for item in val]
    if isinstance(val, dict):
        return {k: _serialize_result(v) for k, v in val.items()}
    return val


def _list_jobs_handler(
    pipeline: ExecutionPipeline,
    status: str | None,
    run_id: str | None,
    user_id: str,
    elevate: bool,
) -> list[dict[str, Any]]:
    """Dispatch and filter ListJobsQuery results.

    Args:
        pipeline: Central execution pipeline.
        status: Optional state filter.
        run_id: Optional run filter.
        user_id: Requesting user identity.
        elevate: Administrative elevation flag.

    Returns:
        List of serialized job records.
    """
    qry = ListJobsQuery(run_id=run_id, user_id=user_id, elevate=elevate)
    jobs: list[JobSpec] = pipeline.execute(qry)
    if not status:
        return [_serialize_result(j) for j in jobs]
    target_status = status.upper().strip()
    return [
        _serialize_result(j)
        for j in jobs
        if j.status.state.name.upper() == target_status
        or str(j.status.state.value).upper() == target_status
    ]


def _submit_run_handler(
    pipeline: ExecutionPipeline,
    run_name: str,
    jobs: list[dict[str, Any]],
    dependencies: dict[str, list[str]] | None,
    user_id: str,
    elevate: bool,
    run_id: str | None,
) -> dict[str, Any]:
    """Normalize and dispatch SubmitRunCommand.

    Args:
        pipeline: Central execution pipeline.
        run_name: Pipeline run title.
        jobs: Constituent job specification dicts.
        dependencies: Optional adjacency map.
        user_id: Submitting user identity.
        elevate: Administrative elevation flag.
        run_id: Custom run identifier.

    Returns:
        Serialized RunStatusReport.
    """
    norm_jobs: list[dict[str, Any]] = []
    for idx, job_raw in enumerate(jobs):
        j_copy = dict(job_raw)
        if "id" not in j_copy:
            j_copy["id"] = f"{run_id or 'run'}-job-{idx + 1}"
        if "user" not in j_copy and user_id:
            j_copy["user"] = user_id
        norm_jobs.append(j_copy)

    payload: dict[str, Any] = {
        "name": run_name,
        "jobs": norm_jobs,
        "dependencies": dependencies or {},
        "user_id": user_id,
        "elevate": elevate,
    }
    if run_id:
        payload["id"] = run_id

    cmd = SubmitRunCommand.model_validate(payload)
    res = pipeline.execute(cmd)
    return _serialize_result(res)


def _get_run_status_handler(
    pipeline: ExecutionPipeline,
    run_id: str,
    user_id: str,
    elevate: bool,
) -> dict[str, Any]:
    """Dispatch GetRunStatusQuery.

    Args:
        pipeline: Central execution pipeline.
        run_id: Pipeline run identifier.
        user_id: Requesting user identity.
        elevate: Administrative elevation flag.

    Returns:
        Serialized RunStatusReport.
    """
    qry = GetRunStatusQuery(run_id=run_id, user_id=user_id, elevate=elevate)
    res = pipeline.execute(qry)
    return _serialize_result(res)


def _lease_task_handler(
    pipeline: ExecutionPipeline,
    worker_id: str,
    task_names: list[str] | None,
    lease_duration_seconds: float,
    queue: str,
    user_id: str,
    elevate: bool,
) -> dict[str, Any] | None:
    """Acquire task lease on the next available pending job.

    Args:
        pipeline: Central execution pipeline.
        worker_id: Worker claiming the lease.
        task_names: Optional task names filter.
        lease_duration_seconds: Lease expiration window.
        queue: Target queue partition name.
        user_id: Worker identity.
        elevate: Administrative elevation flag.

    Returns:
        Serialized TaskRecordResponse or None.
    """
    qry = ListJobsQuery(user_id=user_id, elevate=elevate)
    jobs: list[JobSpec] = pipeline.execute(qry)
    now_ts = datetime.now(UTC).timestamp()
    for j in jobs:
        if j.status.state != JobState.PENDING:
            continue
        if task_names and j.name not in task_names:
            continue
        record = TaskRecordResponse(
            id=j.id,
            task_name=j.name,
            payload={},
            state="RUNNING",
            priority=j.priority,
            attempts=1,
            lease_owner=worker_id,
            lease_expires_at=now_ts + lease_duration_seconds,
            created_at=j.created_at.timestamp(),
        )
        return _serialize_result(record)
    return None


def _get_cluster_nodes_handler(
    pipeline: ExecutionPipeline,
    user_id: str,
    elevate: bool,
) -> dict[str, Any]:
    """Dispatch ListComputeNodesQuery.

    Args:
        pipeline: Central execution pipeline.
        user_id: Requesting user identity.
        elevate: Administrative elevation flag.

    Returns:
        Serialized NodesReport.
    """
    qry = ListComputeNodesQuery(user_id=user_id, elevate=elevate)
    res = pipeline.execute(qry)
    return _serialize_result(res)


def _stream_logs_handler(
    pipeline: ExecutionPipeline,
    job_id: str,
    tail: int | None,
    user_id: str,
    elevate: bool,
) -> list[dict[str, Any]]:
    """Dispatch GetLogsQuery.

    Args:
        pipeline: Central execution pipeline.
        job_id: Target job identifier.
        tail: Tail lines count.
        user_id: Requesting user identity.
        elevate: Administrative elevation flag.

    Returns:
        List of serialized LogChunk dicts.
    """
    qry = GetLogsQuery(job_id=job_id, tail=tail, user_id=user_id, elevate=elevate)
    res = pipeline.execute(qry)
    return _serialize_result(res)


def create_mcp_server(
    pipeline: ExecutionPipeline,
    name: str = "hexaqueue-mcp",
    config: McpConfig | None = None,
) -> FastMCP:
    """Create a FastMCP server exposing Hexaqueue CQRS bus capabilities as tools.

    Notes/Architectural Intent:
        Exposes cluster state, job lifecycle queries, DAG submission, and log streaming
        as Model Context Protocol tools to AI coding assistants (Antigravity, Cursor, Claude).
        Preserves the Principle of Least Privilege: callers authenticate with natural user
        identity or explicit administrative elevation (`elevate=True`).
        Honors McpConfig tool toggles and read-only constraints.

    Args:
        pipeline: Central ExecutionPipeline instance for CQRS dispatching.
        name: Name identifier for the MCP server.
        config: Optional McpConfig configuring enabled tools and security presets.

    Returns:
        Configured FastMCP instance with registered tools.
    """
    server = FastMCP(name=name)
    cfg = config or McpConfig()
    tool_cfg = cfg.tools

    def hq_list_jobs(
        status: str | None = None,
        run_id: str | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[dict[str, Any]]:
        """Query active, pending, running, or failed cluster jobs with status filters.

        Notes/Architectural Intent:
            Dispatches ListJobsQuery via the execution pipeline and filters returned
            JobSpec instances by lifecycle state. Preserves tenant isolation unless elevated.

        Args:
            status: Optional lifecycle state filter (e.g. 'PENDING', 'RUNNING', 'COMPLETED', 'FAILED').
            run_id: Optional parent pipeline run identifier.
            user_id: Natural requesting user identity.
            elevate: Explicit administrative privilege elevation flag.

        Returns:
            List of serialized job records containing id, name, status, and resource attributes.
        """
        return _list_jobs_handler(pipeline, status, run_id, user_id, elevate)

    def hq_submit_run(
        run_name: str,
        jobs: list[dict[str, Any]],
        dependencies: dict[str, list[str]] | None = None,
        user_id: str = "default",
        elevate: bool = False,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit a multi-step workflow DAG or test suite to Hexaqueue.

        Notes/Architectural Intent:
            Constructs and dispatches SubmitRunCommand through ExecutionPipeline
            to schedule a pipeline run across compute clusters.

        Args:
            run_name: Human-readable name for the pipeline run.
            jobs: List of job specification dictionaries (e.g. [{'name': 'step1', 'command': 'pytest'}]).
            dependencies: Optional adjacency map of child_job_id -> list[parent_job_ids].
            user_id: Submitting user identity.
            elevate: Explicit administrative elevation flag.
            run_id: Optional custom run identifier.

        Returns:
            Dictionary representation of initial RunStatusReport.
        """
        return _submit_run_handler(
            pipeline, run_name, jobs, dependencies, user_id, elevate, run_id
        )

    def hq_get_run_status(
        run_id: str,
        user_id: str = "default",
        elevate: bool = False,
    ) -> dict[str, Any]:
        """Retrieve detailed execution progress, completed steps, and failure traces for a run.

        Notes/Architectural Intent:
            Dispatches GetRunStatusQuery through the execution pipeline to return
            aggregated run state, step breakdown, and terminal statuses.

        Args:
            run_id: Pipeline run identifier.
            user_id: Requesting user identity.
            elevate: Explicit administrative elevation flag.

        Returns:
            Dictionary representation of RunStatusReport detailing state and step progress.
        """
        return _get_run_status_handler(pipeline, run_id, user_id, elevate)

    def hq_lease_task(
        worker_id: str,
        task_names: list[str] | None = None,
        lease_duration_seconds: float = 30.0,
        queue: str = "default",
        user_id: str = "default",
        elevate: bool = False,
    ) -> dict[str, Any] | None:
        """Lease the next available task from worker queue.

        Notes/Architectural Intent:
            Dispatches ListJobsQuery to identify the highest priority pending job matching
            worker requirements, returning a TaskRecordResponse lease contract.

        Args:
            worker_id: Unique worker agent identifier claiming the lease.
            task_names: Optional whitelist of task names the worker can process.
            lease_duration_seconds: Duration in seconds before lease expires if not renewed.
            queue: Target queue partition name.
            user_id: Requesting worker or tenant identity.
            elevate: Explicit administrative elevation flag.

        Returns:
            Dictionary representation of leased TaskRecordResponse, or None if no tasks are available.
        """
        return _lease_task_handler(
            pipeline,
            worker_id,
            task_names,
            lease_duration_seconds,
            queue,
            user_id,
            elevate,
        )

    def hq_get_cluster_nodes(
        user_id: str = "default",
        elevate: bool = False,
    ) -> dict[str, Any]:
        """Inspect cluster node profiles, GPU allocations, and resource utilization.

        Notes/Architectural Intent:
            Dispatches ListComputeNodesQuery through the execution pipeline to inspect
            registered worker node profiles, hardware specifications, and states.

        Args:
            user_id: Requesting user identity.
            elevate: Explicit administrative elevation flag.

        Returns:
            Dictionary representation of NodesReport containing total nodes and node profiles.
        """
        return _get_cluster_nodes_handler(pipeline, user_id, elevate)

    def hq_stream_logs(
        job_id: str,
        tail: int | None = None,
        user_id: str = "default",
        elevate: bool = False,
    ) -> list[dict[str, Any]]:
        """Stream recent stdout/stderr chunks for a specific job.

        Notes/Architectural Intent:
            Dispatches GetLogsQuery through the execution pipeline, enforcing tenant
            ownership checks unless administrative elevation is asserted.

        Args:
            job_id: Unique job identifier.
            tail: Optional count of most recent log chunks to retrieve.
            user_id: Requesting user identity.
            elevate: Explicit administrative elevation flag.

        Returns:
            List of serialized log chunk dictionaries containing stream, content, offset, and timestamp.
        """
        return _stream_logs_handler(pipeline, job_id, tail, user_id, elevate)

    if tool_cfg.list_jobs:
        server.add_tool(
            hq_list_jobs, name="hq_list_jobs", description=hq_list_jobs.__doc__
        )
    if tool_cfg.submit_run:
        server.add_tool(
            hq_submit_run, name="hq_submit_run", description=hq_submit_run.__doc__
        )
    if tool_cfg.get_run_status:
        server.add_tool(
            hq_get_run_status,
            name="hq_get_run_status",
            description=hq_get_run_status.__doc__,
        )
    if tool_cfg.lease_task:
        server.add_tool(
            hq_lease_task, name="hq_lease_task", description=hq_lease_task.__doc__
        )
    if tool_cfg.get_cluster_nodes:
        server.add_tool(
            hq_get_cluster_nodes,
            name="hq_get_cluster_nodes",
            description=hq_get_cluster_nodes.__doc__,
        )
    if tool_cfg.stream_logs:
        server.add_tool(
            hq_stream_logs, name="hq_stream_logs", description=hq_stream_logs.__doc__
        )

    return server


def mount_mcp_server(
    app: Any,
    pipeline: ExecutionPipeline,
    config: McpConfig | None = None,
    path_prefix: str = "/mcp",
    sse_path: str = "/sse",
    auth_token: str | None = None,
) -> FastMCP:
    """Mount FastMCP server SSE endpoints onto a FastAPI/Starlette application.

    Notes/Architectural Intent:
        Exposes Hexaqueue CQRS bus tools over Model Context Protocol SSE transport,
        allowing remote AI coding assistants to connect at /mcp/sse.
        Honors McpConfig parameters and per-tool enablement filters.

    Args:
        app: Target FastAPI or Starlette application.
        pipeline: Central ExecutionPipeline instance.
        config: Optional McpConfig configuring paths, security tokens, and tools.
        path_prefix: Route prefix where MCP is mounted (defaults to '/mcp').
        sse_path: SSE stream endpoint path (defaults to '/sse').
        auth_token: Optional Bearer authentication secret.

    Returns:
        Configured FastMCP server instance.
    """
    cfg = config or McpConfig()
    server = create_mcp_server(pipeline, config=cfg)
    prefix = cfg.path_prefix or path_prefix
    sse = cfg.sse_path or sse_path
    token = cfg.auth_token or auth_token
    mount_mcp_sse(
        app=app,
        server=server,
        path_prefix=prefix,
        sse_path=sse,
        auth_token=token,
    )
    return server


def run_mcp_stdio(
    pipeline: ExecutionPipeline,
    name: str = "hexaqueue-mcp",
    config: McpConfig | None = None,
) -> None:
    """Execute the MCP stdio communication loop synchronously.

    Notes/Architectural Intent:
        Driving entrypoint for AI coding assistants (Claude Desktop, Antigravity,
        Cursor) invoking Hexaqueue as a local subprocess.

    Args:
        pipeline: Central ExecutionPipeline instance.
        name: Name of the MCP server.
        config: Optional McpConfig configuring enabled tools and read-only mode.
    """
    server = create_mcp_server(pipeline, name=name, config=config)
    run_stdio_server(server)


async def run_mcp_stdio_async(
    pipeline: ExecutionPipeline,
    name: str = "hexaqueue-mcp",
    config: McpConfig | None = None,
) -> None:
    """Execute the MCP stdio communication loop asynchronously.

    Notes/Architectural Intent:
        Asynchronous variant for executing the MCP stdio event loop.

    Args:
        pipeline: Central ExecutionPipeline instance.
        name: Name of the MCP server.
        config: Optional McpConfig configuring enabled tools and read-only mode.
    """
    server = create_mcp_server(pipeline, name=name, config=config)
    await run_stdio_async(server)
