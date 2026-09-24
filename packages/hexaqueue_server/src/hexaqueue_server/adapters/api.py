"""FastAPI REST presentation adapter for Hexaqueue Server.

Notes/Architectural Intent:
    Exposes OpenAPI routes for all Hexaqueue capabilities with 100% surface parity
    to CLI and Web Dashboard. Implements the Principle of Least Privilege:
    callers act under their natural identity by default, with administrative
    elevation asserted explicitly via header (`X-Hexaqueue-Elevate: true`) or
    query parameter (`?elevate=true`).
"""

from typing import Annotated, Any
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    status,
)
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.adapters.dependencies import get_pipeline
from hexastack_fastapi.infra import create_fastapi_app
from rodi import Container

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
    GetRunStatusQuery,
    HoldJobCommand,
    ListJobsQuery,
    RegisterCollateralCommand,
    ReleaseJobCommand,
    SettleBudgetCommand,
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
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.domain.models import RunStatusReport
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline
from hexaqueue_worker.domain.pty import PtySessionInfo
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


def _resolve_auth(
    header_user: str | None,
    query_user: str | None,
    header_elevate: bool,
    query_elevate: bool,
) -> tuple[str, bool]:
    """Resolve requesting user identity and elevation status.

    Args:
        header_user: User identity from X-Hexaqueue-User header.
        query_user: User identity from user query parameter.
        header_elevate: Elevation flag from X-Hexaqueue-Elevate header.
        query_elevate: Elevation flag from elevate query parameter.

    Returns:
        Tuple of (resolved_user_id, is_elevated).
    """
    user_id = header_user or query_user or "default"
    elevate = header_elevate or query_elevate
    return user_id, elevate


def _dispatch(pipeline: ExecutionPipeline, message: Any) -> Any:
    """Execute a CQRS message through the pipeline, mapping domain exceptions to HTTP.

    Args:
        pipeline: ExecutionPipeline instance.
        message: Command or Query instance.

    Returns:
        Evaluated domain result.

    Raises:
        HTTPException: With 403 on PermissionDeniedError or 400 on domain errors.
    """
    try:
        return pipeline.execute(message)
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except HexaqueueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


def create_server_api_router() -> APIRouter:
    """Construct the FastAPI APIRouter providing unified REST endpoints for Hexaqueue.

    Returns:
        APIRouter with all /v1 endpoints bound to CQRS pipeline dispatch.
    """
    router = APIRouter(prefix="/v1")

    # 1. Run Submission
    @router.post(
        "/runs",
        response_model=RunStatusReport,
        status_code=status.HTTP_201_CREATED,
        summary="Submit pipeline DAG run",
    )
    def submit_run(
        cmd: SubmitRunCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    ) -> RunStatusReport:
        user_id, elevate = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, False
        )
        effective_cmd = SubmitRunCommand(
            run_spec=cmd.run_spec,
            jobs=cmd.jobs,
            dependencies=cmd.dependencies,
            user_id=cmd.user_id if cmd.user_id != "default" else user_id,
            elevate=cmd.elevate or elevate,
        )
        return _dispatch(pipeline, effective_cmd)

    # 2. Run Status
    @router.get(
        "/runs/{run_id}",
        response_model=RunStatusReport,
        summary="Get run status",
    )
    def get_run_status(
        run_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> RunStatusReport:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, elevate
        )
        qry = GetRunStatusQuery(run_id=run_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    # 3. Cancel Run
    @router.post(
        "/runs/{run_id}/cancel",
        response_model=RunStatusReport,
        summary="Cancel pipeline run",
    )
    def cancel_run(
        run_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> RunStatusReport:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, elevate
        )
        cmd = CancelRunCommand(run_id=run_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, cmd)

    # 4. Suite Submission
    @router.post(
        "/suites",
        response_model=RunStatusReport,
        status_code=status.HTTP_201_CREATED,
        summary="Submit hierarchical suite workload",
    )
    def submit_suite(
        cmd: SubmitSuiteCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    ) -> RunStatusReport:
        user_id, elevate = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, False
        )
        effective_cmd = SubmitSuiteCommand(
            suite_spec=cmd.suite_spec,
            user_id=cmd.user_id if cmd.user_id != "default" else user_id,
            elevate=cmd.elevate or elevate,
        )
        return _dispatch(pipeline, effective_cmd)

    # 5. List Jobs
    @router.get(
        "/jobs",
        response_model=list[JobSpec],
        summary="List registered jobs",
    )
    def list_jobs(
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        run_id: Annotated[str | None, Query()] = None,
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> list[JobSpec]:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, elevate
        )
        qry = ListJobsQuery(run_id=run_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    # 6. Get Job
    @router.get(
        "/jobs/{job_id}",
        response_model=JobSpec,
        summary="Get job metadata and status",
    )
    def get_job(
        job_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> JobSpec:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, elevate
        )
        qry = GetJobQuery(job_id=job_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    # 7. Job Lifecycle Controls (Hold, Release, Cancel)
    @router.post(
        "/jobs/{job_id}/hold",
        response_model=JobSpec,
        summary="Place hold on job",
    )
    def hold_job(
        job_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> JobSpec:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, elevate
        )
        cmd = HoldJobCommand(job_id=job_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, cmd)

    @router.post(
        "/jobs/{job_id}/release",
        response_model=JobSpec,
        summary="Release hold on job",
    )
    def release_job(
        job_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> JobSpec:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, elevate
        )
        cmd = ReleaseJobCommand(job_id=job_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, cmd)

    @router.post(
        "/jobs/{job_id}/cancel",
        response_model=JobSpec,
        summary="Cancel individual job",
    )
    def cancel_job(
        job_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> JobSpec:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, elevate
        )
        cmd = CancelJobCommand(job_id=job_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, cmd)

    # 8. Explainability
    @router.get(
        "/jobs/{job_id}/explain",
        response_model=SchedulingDecisionReport,
        summary="Explain scheduling decision for job",
    )
    def explain_job(
        job_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        admin: Annotated[bool, Query()] = False,
    ) -> SchedulingDecisionReport:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, admin
        )
        qry = ExplainJobQuery(
            job_id=job_id, requesting_user=user_id, is_admin=is_elevated
        )
        return _dispatch(pipeline, qry)

    # 9. Logs
    @router.get(
        "/jobs/{job_id}/logs",
        response_model=list[LogChunk],
        summary="Get job execution logs",
    )
    def get_logs(
        job_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        tail: Annotated[int | None, Query()] = None,
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    ) -> list[LogChunk]:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, False
        )
        qry = GetLogsQuery(
            job_id=job_id, tail=tail, user_id=user_id, elevate=is_elevated
        )
        return _dispatch(pipeline, qry)

    # 10. Interactive PTY Session
    @router.post(
        "/jobs/{job_id}/pty",
        response_model=PtySessionInfo,
        summary="Create interactive PTY attach session",
    )
    def create_pty(
        job_id: str,
        cmd: CreatePtySessionCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    ) -> PtySessionInfo:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, cmd.elevate
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
        return _dispatch(pipeline, effective_cmd)

    # 11. Fair-Share Tree
    @router.get(
        "/fairshare",
        response_model=FairShareTreeReport,
        summary="Get fair-share hierarchy tree",
    )
    def get_fairshare_tree(
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        admin: Annotated[bool, Query()] = False,
    ) -> FairShareTreeReport:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, admin
        )
        qry = GetFairShareTreeQuery(requesting_user=user_id, is_admin=is_elevated)
        return _dispatch(pipeline, qry)

    # 12. Nodes Telemetry
    @router.get(
        "/nodes",
        response_model=list[NodeTelemetryPulse],
        summary="Get registered compute worker nodes",
    )
    def get_nodes(
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> list[NodeTelemetryPulse]:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, elevate
        )
        qry = GetNodesQuery(user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    # 13. Cluster Queue Statistics
    @router.get(
        "/stats",
        response_model=ClusterStatsReport,
        summary="Get aggregate cluster queue statistics",
    )
    def get_stats(
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> ClusterStatsReport:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, elevate
        )
        qry = GetQueueStatsQuery(user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    # 14. Node Bastion SSH Terminal
    @router.post(
        "/nodes/{node_id}/ssh",
        response_model=PtySessionInfo,
        summary="Launch secure bastion shell on node",
    )
    def create_bastion_ssh(
        node_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
        elevate: Annotated[bool, Query()] = False,
    ) -> PtySessionInfo:
        user_id, is_elevated = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, elevate
        )
        cmd = CreateBastionSessionCommand(
            node_id=node_id,
            session_id=f"bastion-{uuid4().hex[:8]}",
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, cmd)

    # 15. Collateral Ingestion
    @router.post(
        "/collateral/upload",
        response_model=CollateralBundle,
        summary="Register and stage collateral artifact",
    )
    def register_collateral(
        cmd: RegisterCollateralCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    ) -> CollateralBundle:
        user_id, elevate = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, False
        )
        effective_cmd = RegisterCollateralCommand(
            name=cmd.name,
            version=cmd.version,
            checksum_sha256=cmd.checksum_sha256,
            size_bytes=cmd.size_bytes,
            tier=cmd.tier,
            kind=cmd.kind,
            target_path=cmd.target_path,
            user_id=cmd.user_id if cmd.user_id != "default" else user_id,
            elevate=cmd.elevate or elevate,
        )
        return _dispatch(pipeline, effective_cmd)

    # 16. Budget Settlement
    @router.post(
        "/budget/settle",
        response_model=dict[str, Any],
        summary="Settle project compute consumption",
    )
    def settle_budget(
        cmd: SettleBudgetCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        x_hexaqueue_user: Annotated[str | None, Header()] = None,
        x_hexaqueue_elevate: Annotated[bool, Header()] = False,
    ) -> dict[str, Any]:
        user_id, elevate = _resolve_auth(
            x_hexaqueue_user, None, x_hexaqueue_elevate, False
        )
        effective_cmd = SettleBudgetCommand(
            project_id=cmd.project_id,
            amount_cents=cmd.amount_cents,
            user_id=cmd.user_id if cmd.user_id != "default" else user_id,
            elevate=cmd.elevate or elevate,
        )
        return _dispatch(pipeline, effective_cmd)

    return router


def create_server_app(
    pipeline: ExecutionPipeline | None = None,
) -> FastAPI:
    """Create a fully assembled FastAPI application for Hexaqueue Server.

    Args:
        pipeline: Optional pre-configured ExecutionPipeline.

    Returns:
        Configured FastAPI application instance.
    """
    effective_pipeline = pipeline
    if effective_pipeline is None:
        from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter

        queue = InMemoryJobQueueAdapter()
        controller = LocalSchedulerControllerAdapter(queue=queue)
        effective_pipeline = create_hexaqueue_execution_pipeline(controller)

    container = Container()
    container.register(ExecutionPipeline, instance=effective_pipeline)

    app = create_fastapi_app(container=container, pipeline=effective_pipeline)
    api_router = create_server_api_router()
    app.include_router(api_router)
    return app


__all__ = [
    "create_server_api_router",
    "create_server_app",
]
