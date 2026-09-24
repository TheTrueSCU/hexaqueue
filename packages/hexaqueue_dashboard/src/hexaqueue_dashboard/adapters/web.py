"""Web dashboard presentation adapter for Hexaqueue cluster operations.

Notes/Architectural Intent:
    Serves as the primary HTTP presentation router for the Web Dashboard.
    Directly dispatches commands and queries into the shared `ExecutionPipeline`,
    guaranteeing 100% surface parity with the CLI and REST APIs without
    introducing private domain bypasses or state drift.
"""

from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
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


def _resolve_auth(
    header_user: str | None,
    header_elevate: bool,
    query_elevate: bool,
) -> tuple[str, bool]:
    """Resolve requesting user identity and elevation status.

    Args:
        header_user: User identity from header.
        header_elevate: Elevation flag from header.
        query_elevate: Elevation flag from query string.

    Returns:
        Tuple of (user_id, is_elevated).
    """
    user_id = header_user if header_user else "default"
    elevate = bool(header_elevate or query_elevate)
    return user_id, elevate


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
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> FairShareTreeReport:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, x_hexaqueue_elevate, elevate
        )
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
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    ) -> RunStatusReport:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, x_hexaqueue_elevate, False
        )
        effective_cmd = SubmitRunCommand(
            run_spec=cmd.run_spec,
            jobs=cmd.jobs,
            dependencies=cmd.dependencies,
            user_id=cmd.user_id if cmd.user_id != "default" else user_id,
            elevate=cmd.elevate or is_elevated,
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
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    ) -> RunStatusReport:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, x_hexaqueue_elevate, False
        )
        effective_cmd = SubmitSuiteCommand(
            suite_spec=cmd.suite_spec,
            user_id=cmd.user_id if cmd.user_id != "default" else user_id,
            elevate=cmd.elevate or is_elevated,
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
        run_id: Annotated[str | None, Query()] = None,
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> list[JobSpec]:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, x_hexaqueue_elevate, elevate
        )
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
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> JobSpec:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, x_hexaqueue_elevate, elevate
        )
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
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> SchedulingDecisionReport:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, x_hexaqueue_elevate, elevate
        )
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
        tail: Annotated[int | None, Query()] = None,
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> list[LogChunk]:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, x_hexaqueue_elevate, elevate
        )
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
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    ) -> JobSpec:
        user_id, header_elevate = _resolve_auth(
            x_hexaqueue_user, x_hexaqueue_elevate, False
        )
        is_elevated = action_req.elevate or header_elevate
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
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    ) -> PtySessionInfo:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, x_hexaqueue_elevate, cmd.elevate
        )
        effective_cmd = CreatePtySessionCommand(
            job_id=job_id,
            session_id=cmd.session_id or f"pty-{uuid4().hex[:8]}",
            command=cmd.command,
            user_id=cmd.user_id if cmd.user_id != "default" else user_id,
            elevate=is_elevated,
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
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    ) -> CollateralBundle:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, x_hexaqueue_elevate, False
        )
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
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    ) -> PtySessionInfo:
        user_id, header_elevate = _resolve_auth(
            x_hexaqueue_user, x_hexaqueue_elevate, False
        )
        is_elevated = req.elevate or header_elevate
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
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> RunStatusReport:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, x_hexaqueue_elevate, elevate
        )
        return _dispatch(
            pip,
            CancelRunCommand(run_id=run_id, user_id=user_id, elevate=is_elevated),
        )

    return router


__all__ = [
    "create_dashboard_router",
    "get_pipeline",
]
