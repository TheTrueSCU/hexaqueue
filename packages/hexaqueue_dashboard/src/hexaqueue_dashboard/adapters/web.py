"""Web dashboard presentation adapter for Hexaqueue cluster operations.

Notes/Architectural Intent:
    Serves as the primary HTTP presentation router for the Web Dashboard.
    Directly dispatches commands and queries into the shared `ExecutionPipeline`,
    guaranteeing 100% surface parity with the CLI and REST APIs without
    introducing private domain bypasses or state drift.
"""

import asyncio
import json
import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated, Any, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from hexastack_cqrs.infra.pipeline import ExecutionPipeline

from hexaqueue_core.domain.collateral import CollateralBundle
from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CancelRunCommand,
    ClusterStatsReport,
    CreateBastionSessionCommand,
    CreatePtySessionCommand,
    ExplainJobQuery,
    GetFairShareTreeQuery,
    GetJobQuery,
    GetLogsQuery,
    GetNodesQuery,
    GetQueueStatsQuery,
    HoldJobCommand,
    ListJobsQuery,
    RegisterCollateralCommand,
    ReleaseJobCommand,
    SubmitRunCommand,
    SubmitSuiteCommand,
)
from hexaqueue_core.domain.exceptions import (
    HexaqueueError,
    PermissionDeniedError,
)
from hexaqueue_core.domain.explainability import (
    FairShareTreeReport,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_dashboard.adapters.auth import (
    create_auth_router,
    enforce_https_transport,
    extract_bearer_or_cookie_token,
    get_auth_manager,
)
from hexaqueue_dashboard.domain.models import (
    DashboardBastionRequest,
    DashboardCollateralRequest,
    DashboardJobAction,
    DashboardOverviewReport,
)
from hexaqueue_server.domain.models import RunStatusReport
from hexaqueue_worker.domain.pty import PtySessionInfo
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


def get_pipeline(request: Request) -> ExecutionPipeline:
    """Extract ExecutionPipeline from FastAPI application state.

    Args:
        request: Active incoming HTTP request.

    Returns:
        Configured ExecutionPipeline instance.

    Raises:
        HTTPException: If execution pipeline is not registered in state.
    """
    pipeline = getattr(request.app.state, "pipeline", None)
    if pipeline is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="ExecutionPipeline is not configured in application state.",
        )
    return pipeline


def get_auth_context(
    x_hexaqueue_user: Annotated[str | None, Header()] = None,
    user: Annotated[str | None, Query()] = None,
    x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    elevate: Annotated[bool, Query()] = False,
    x_hexaqueue_admin_token: Annotated[str | None, Header()] = None,
    admin_token: Annotated[str | None, Query()] = None,
    request: Request = cast("Request", None),
) -> tuple[str, bool]:
    """Resolve requesting user identity and elevation status via `hexastack-auth`.

    Args:
        request: Active incoming HTTP request (optional for direct unit calls).
        x_hexaqueue_user: Legacy user identity header (only when anonymous mode enabled).
        user: Legacy user identity query param (only when anonymous mode enabled).
        x_hexaqueue_elevate: Legacy elevation header.
        elevate: Legacy elevation query param.
        x_hexaqueue_admin_token: Legacy administrative elevation token header.
        admin_token: Legacy administrative elevation token query param.

    Returns:
        Tuple of (user_id, is_elevated).

    Raises:
        HTTPException: 401 if unauthenticated, or 403 if HTTPS/elevation check fails.

    Notes/Architectural Intent:
        Prefers signed `hexastack-auth` JWTs (via Bearer header or HttpOnly session
        cookie) and enforces HTTPS for non-loopback requests. Only falls back to
        header identity when `HEXAQUEUE_ALLOW_ANONYMOUS_ADMIN=1` is explicitly set.
    """
    if request is not None:
        enforce_https_transport(request)
        token = extract_bearer_or_cookie_token(request)
        if token is not None:
            identity = get_auth_manager(request).verify_token(token)
            return identity.user_id, "admin" in identity.roles

        if os.environ.get("HEXAQUEUE_ALLOW_ANONYMOUS_ADMIN", "0") != "1":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required: provide a valid Bearer token or session cookie.",
            )

    user_id = x_hexaqueue_user or user or "default"
    requested_elevation = bool(x_hexaqueue_elevate or elevate)
    if requested_elevation:
        configured_token = os.environ.get("HEXAQUEUE_ADMIN_TOKEN")
        if configured_token is not None:
            provided_token = x_hexaqueue_admin_token or admin_token
            if provided_token != configured_token:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid or missing administrative elevation token.",
                )
        elif os.environ.get("HEXAQUEUE_ALLOW_ANONYMOUS_ADMIN", "0") != "1":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrative elevation requires HEXAQUEUE_ADMIN_TOKEN to be configured.",
            )
        is_elevated = True
    else:
        is_elevated = False
    return user_id, is_elevated


def _allow_body_elevation(request: Request | None) -> tuple[bool, bool]:
    """Determine whether a request carries a JWT and whether body elevation is permitted."""
    has_jwt = (
        request is not None and extract_bearer_or_cookie_token(request) is not None
    )
    allow_body = request is None or (
        os.environ.get("HEXAQUEUE_ALLOW_ANONYMOUS_ADMIN", "0") == "1" and not has_jwt
    )
    return has_jwt, allow_body


def _resolve_action_elevation(
    action_req: DashboardJobAction,
    header_elevate: bool,
    request: Request | None,
) -> bool:
    """Resolve effective elevation flag for job lifecycle actions without RBAC bypass."""
    if not action_req.elevate or header_elevate:
        return header_elevate
    has_jwt, _ = _allow_body_elevation(request)
    configured_token = os.environ.get("HEXAQUEUE_ADMIN_TOKEN")
    if configured_token is not None and not has_jwt:
        if action_req.admin_token != configured_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or missing administrative elevation token.",
            )
        return True
    if os.environ.get("HEXAQUEUE_ALLOW_ANONYMOUS_ADMIN", "0") == "1" and not has_jwt:
        return True
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Administrative role ('admin') is required for elevation.",
    )


def _dispatch[T](pipeline: ExecutionPipeline, msg: Any) -> T:
    """Dispatch a message through the ExecutionPipeline and translate domain exceptions.

    Args:
        pipeline: Target CQRS pipeline.
        msg: Command or Query instance.

    Returns:
        Evaluated result from pipeline handler.

    Raises:
        HTTPException: Translated HTTP exception for API response.
    """
    try:
        return pipeline.execute(msg)  # type: ignore[no-any-return]
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except HexaqueueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc


def _build_sse_snapshot(
    pipeline: ExecutionPipeline, user_id: str, is_elevated: bool
) -> dict[str, Any]:
    """Build a serializable cluster snapshot for dashboard SSE streaming."""
    stats: ClusterStatsReport = _dispatch(pipeline, GetQueueStatsQuery())
    nodes: list[NodeTelemetryPulse] = _dispatch(pipeline, GetNodesQuery())
    jobs: list[JobSpec] = _dispatch(
        pipeline, ListJobsQuery(user_id=user_id, elevate=is_elevated)
    )
    return {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "stats": stats.model_dump(mode="json"),
        "nodes_count": len(nodes),
        "jobs": [
            {
                "id": j.id,
                "run_id": j.run_id,
                "name": j.name,
                "state": str(j.state),
                "outcome": str(j.outcome) if j.outcome is not None else None,
            }
            for j in jobs
        ],
    }


async def _stream_dashboard_events_generator(
    request: Request,
    pipeline: ExecutionPipeline,
    user_id: str,
    is_elevated: bool,
    poll_interval: float,
    once: bool,
) -> AsyncGenerator[str]:
    """Yield SSE-formatted cluster snapshots and idle heartbeats."""
    last_fingerprint: str | None = None
    while True:
        if await request.is_disconnected():
            break
        snapshot = await asyncio.to_thread(
            _build_sse_snapshot, pipeline, user_id, is_elevated
        )
        stats_dict = snapshot["stats"]
        fingerprint = json.dumps(
            {
                "stats": {k: v for k, v in stats_dict.items() if k != "timestamp"},
                "nodes_count": snapshot["nodes_count"],
                "jobs": snapshot["jobs"],
            },
            sort_keys=True,
        )
        if last_fingerprint is None or fingerprint != last_fingerprint:
            event_name = "snapshot" if last_fingerprint is None else "cluster_update"
            last_fingerprint = fingerprint
            yield f"event: {event_name}\ndata: {json.dumps(snapshot)}\n\n"
        else:
            heartbeat = {"timestamp": snapshot["timestamp"]}
            yield f"event: heartbeat\ndata: {json.dumps(heartbeat)}\n\n"
        if once:
            break
        await asyncio.sleep(poll_interval)


def create_dashboard_router(
    pipeline: ExecutionPipeline | None = None,
) -> APIRouter:
    """Create and configure the Web Dashboard presentation router.

    Args:
        pipeline: Optional ExecutionPipeline instance for dependency injection.

    Returns:
        Configured APIRouter instance for dashboard endpoints.

    Notes/Architectural Intent:
        Directly implements all interactive operations displayed on the Web
        Dashboard console, routing each request to the shared CQRS pipeline.
    """
    router = APIRouter(prefix="/dashboard", tags=["Dashboard"])
    router.include_router(create_auth_router())

    # 1. Cluster Overview
    @router.get(
        "/overview",
        response_model=DashboardOverviewReport,
        summary="Cluster dashboard overview",
    )
    def get_overview(
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
    ) -> DashboardOverviewReport:
        stats: ClusterStatsReport = _dispatch(pip, GetQueueStatsQuery())
        nodes: list[NodeTelemetryPulse] = _dispatch(pip, GetNodesQuery())
        return DashboardOverviewReport(
            total_jobs=stats.total_jobs,
            running_jobs=stats.running_jobs,
            pending_jobs=stats.pending_jobs,
            active_workers=len(nodes),
        )

    # 2. Cluster Stats
    @router.get(
        "/stats",
        response_model=ClusterStatsReport,
        summary="Queue and cluster execution metrics",
    )
    def get_stats(
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
    ) -> ClusterStatsReport:
        return _dispatch(pip, GetQueueStatsQuery())

    # 3. Nodes Telemetry
    @router.get(
        "/nodes",
        response_model=list[NodeTelemetryPulse],
        summary="Registered worker nodes",
    )
    def get_nodes(
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
    ) -> list[NodeTelemetryPulse]:
        return _dispatch(pip, GetNodesQuery())

    # 4. Fair-Share Tree
    @router.get(
        "/fairshare",
        response_model=FairShareTreeReport,
        summary="Fair-share tree hierarchy",
    )
    def get_fairshare(
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> FairShareTreeReport:
        user_id, is_elevated = auth
        return _dispatch(
            pip, GetFairShareTreeQuery(requesting_user=user_id, is_admin=is_elevated)
        )

    # 5. Run Submission
    @router.post(
        "/runs/submit",
        response_model=RunStatusReport,
        status_code=status.HTTP_201_CREATED,
        summary="Submit pipeline run via Dashboard",
    )
    def submit_run(
        cmd: SubmitRunCommand,
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> RunStatusReport:
        user_id, is_elevated = auth
        effective_cmd = SubmitRunCommand(
            run_spec=cmd.run_spec,
            jobs=cmd.jobs,
            dependencies=cmd.dependencies,
            user_id=cmd.user_id if cmd.user_id != "default" else user_id,
            elevate=bool(cmd.elevate or is_elevated),
        )
        return _dispatch(pip, effective_cmd)

    # 6. Suite Submission
    @router.post(
        "/suites/submit",
        response_model=RunStatusReport,
        status_code=status.HTTP_201_CREATED,
        summary="Submit suite pipeline via Dashboard",
    )
    def submit_suite(
        cmd: SubmitSuiteCommand,
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> RunStatusReport:
        user_id, is_elevated = auth
        effective_cmd = SubmitSuiteCommand(
            suite_spec=cmd.suite_spec,
            user_id=cmd.user_id if cmd.user_id != "default" else user_id,
            elevate=bool(cmd.elevate or is_elevated),
        )
        return _dispatch(pip, effective_cmd)

    # 7. Job Listing
    @router.get(
        "/jobs",
        response_model=list[JobSpec],
        summary="List jobs in dashboard view",
    )
    def list_jobs(
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
        run_id: Annotated[str | None, Query()] = None,
    ) -> list[JobSpec]:
        user_id, is_elevated = auth
        return _dispatch(
            pip,
            ListJobsQuery(run_id=run_id, user_id=user_id, elevate=is_elevated),
        )

    # 8. Job Detail
    @router.get(
        "/jobs/{job_id}",
        response_model=JobSpec,
        summary="Get single job details",
    )
    def get_job(
        job_id: str,
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> JobSpec:
        user_id, is_elevated = auth
        return _dispatch(
            pip,
            GetJobQuery(job_id=job_id, user_id=user_id, elevate=is_elevated),
        )

    # 9. Explainability
    @router.get(
        "/jobs/{job_id}/explain",
        response_model=SchedulingDecisionReport,
        summary="Explain job priority and scheduling",
    )
    def explain_job(
        job_id: str,
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> SchedulingDecisionReport:
        user_id, is_elevated = auth
        return _dispatch(
            pip,
            ExplainJobQuery(
                job_id=job_id, requesting_user=user_id, is_admin=is_elevated
            ),
        )

    # 10. Execution Logs
    @router.get(
        "/jobs/{job_id}/logs",
        response_model=list[LogChunk],
        summary="Get job execution logs",
    )
    def get_logs(
        job_id: str,
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
        tail: Annotated[int | None, Query()] = None,
    ) -> list[LogChunk]:
        user_id, is_elevated = auth
        return _dispatch(
            pip,
            GetLogsQuery(
                job_id=job_id, tail=tail, user_id=user_id, elevate=is_elevated
            ),
        )

    # 11. Job Lifecycle Action (Hold, Release, Cancel)
    @router.post(
        "/jobs/{job_id}/action",
        response_model=JobSpec,
        summary="Apply job lifecycle action with elevation support",
    )
    def perform_job_action(
        job_id: str,
        action_req: DashboardJobAction,
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
        request: Request = cast("Request", None),
    ) -> JobSpec:
        user_id, header_elevate = auth
        is_elevated = _resolve_action_elevation(action_req, header_elevate, request)
        action = action_req.action.lower()

        if action == "hold":
            cmd_hold = HoldJobCommand(
                job_id=job_id, user_id=user_id, elevate=is_elevated
            )
            return _dispatch(pip, cmd_hold)
        if action == "release":
            cmd_rel = ReleaseJobCommand(
                job_id=job_id, user_id=user_id, elevate=is_elevated
            )
            return _dispatch(pip, cmd_rel)
        if action == "cancel":
            cmd_can = CancelJobCommand(
                job_id=job_id, user_id=user_id, elevate=is_elevated
            )
            return _dispatch(pip, cmd_can)

        msg = f"Unknown lifecycle action '{action_req.action}'. Must be 'hold', 'release', or 'cancel'."
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    # 12. PTY Terminal
    @router.post(
        "/jobs/{job_id}/terminal",
        response_model=PtySessionInfo,
        summary="Open interactive PTY session via Dashboard",
    )
    def create_terminal(
        job_id: str,
        cmd: CreatePtySessionCommand,
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
        request: Request = cast("Request", None),
    ) -> PtySessionInfo:
        user_id, is_elevated = auth
        has_jwt, allow_body_elevate = _allow_body_elevation(request)
        effective_cmd = CreatePtySessionCommand(
            job_id=job_id,
            session_id=cmd.session_id or f"pty-{uuid4().hex[:8]}",
            command=cmd.command,
            user_id=user_id
            if has_jwt
            else (cmd.user_id if cmd.user_id != "default" else user_id),
            elevate=bool(is_elevated or (allow_body_elevate and cmd.elevate)),
            rows=cmd.rows,
            cols=cmd.cols,
            term_type=cmd.term_type,
        )
        return _dispatch(pip, effective_cmd)

    # 13. Collateral Upload Staging
    @router.post(
        "/collateral/upload",
        response_model=CollateralBundle,
        summary="Stage and register collateral asset",
    )
    def upload_collateral(
        req: DashboardCollateralRequest,
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> CollateralBundle:
        user_id, is_elevated = auth
        cmd = RegisterCollateralCommand(
            name=req.name,
            size_bytes=req.size_bytes,
            checksum_sha256=req.checksum_sha256,
            tier=req.tier,
            kind=req.kind,
            target_path=req.target_path,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pip, cmd)

    # 14. Node Bastion SSH
    @router.post(
        "/nodes/{node_id}/ssh",
        response_model=PtySessionInfo,
        summary="Request administrative bastion access to worker node",
    )
    def create_bastion_ssh(
        node_id: str,
        req: DashboardBastionRequest,
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
        request: Request = cast("Request", None),
    ) -> PtySessionInfo:
        user_id, header_elevate = auth
        _, allow_body_elevate = _allow_body_elevation(request)
        is_elevated = bool(header_elevate or (allow_body_elevate and req.elevate))
        session_id = req.session_id or f"bastion-{uuid4().hex[:8]}"
        cmd = CreateBastionSessionCommand(
            node_id=node_id,
            session_id=session_id,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pip, cmd)

    # 15. Cancel Run
    @router.post(
        "/runs/{run_id}/cancel",
        response_model=RunStatusReport,
        summary="Cancel entire pipeline run via Dashboard",
    )
    def cancel_run(
        run_id: str,
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> RunStatusReport:
        user_id, is_elevated = auth
        return _dispatch(
            pip,
            CancelRunCommand(run_id=run_id, user_id=user_id, elevate=is_elevated),
        )

    # 0. Tunnel & Host Heartbeat
    @router.get(
        "/health",
        summary="Lightweight dashboard tunnel & host heartbeat",
    )
    def dashboard_health() -> dict[str, str]:
        """Return lightweight liveness indicator for the dashboard heartbeat widget."""
        return {"status": "live"}

    # 0b. Authenticated Cluster SSE Stream
    @router.get(
        "/events",
        summary="Stream live cluster stats, jobs, and node telemetry deltas via SSE",
        response_class=StreamingResponse,
    )
    async def stream_dashboard_events(
        request: Request,
        pip: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
        poll_interval: Annotated[float, Query(ge=0.1, le=30.0)] = 2.0,
        once: Annotated[bool, Query()] = False,
    ) -> StreamingResponse:
        """Stream authenticated cluster updates as Server-Sent Events."""
        user_id, is_elevated = auth
        return StreamingResponse(
            _stream_dashboard_events_generator(
                request, pip, user_id, is_elevated, poll_interval, once
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router


__all__ = [
    "create_dashboard_router",
    "get_auth_context",
    "get_pipeline",
]
