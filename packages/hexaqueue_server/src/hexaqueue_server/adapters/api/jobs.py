"""Job inspection, lifecycle mutation, explainability, and PTY session REST endpoints.

Notes/Architectural Intent:
    Provides granular job management including administrative hold/release,
    preemption cancellation, multi-factor priority explainability diagnostics,
    and secure pseudo-terminal attach session allocation.
"""

from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    Query,
)
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.adapters.dependencies import get_pipeline

from hexaqueue_core.domain.cqrs import (
    CancelJobCommand,
    CreatePtySessionCommand,
    ExplainJobQuery,
    GetJobQuery,
    HoldJobCommand,
    ListJobsQuery,
    ReleaseJobCommand,
)
from hexaqueue_core.domain.explainability import SchedulingDecisionReport
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_server.adapters.api.auth import get_auth_context
from hexaqueue_server.adapters.api.common import _dispatch
from hexaqueue_worker.domain.pty import PtySessionInfo


def create_jobs_router() -> APIRouter:
    """Construct APIRouter for job operations and lifecycle controls.

    Returns:
        APIRouter with endpoints for jobs inspection, lifecycle, explainability, and PTY.
    """
    router = APIRouter()

    # 1. List Jobs
    @router.get(
        "/jobs",
        response_model=list[JobSpec],
        summary="List registered jobs",
    )
    def list_jobs(
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
        run_id: Annotated[str | None, Query()] = None,
    ) -> list[JobSpec]:
        user_id, is_elevated = auth
        qry = ListJobsQuery(run_id=run_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    # 2. Get Job
    @router.get(
        "/jobs/{job_id}",
        response_model=JobSpec,
        summary="Get job metadata and status",
    )
    def get_job(
        job_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> JobSpec:
        user_id, is_elevated = auth
        qry = GetJobQuery(job_id=job_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    # 3. Hold Job
    @router.post(
        "/jobs/{job_id}/hold",
        response_model=JobSpec,
        summary="Place hold on job",
    )
    def hold_job(
        job_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> JobSpec:
        user_id, is_elevated = auth
        cmd = HoldJobCommand(job_id=job_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, cmd)

    # 4. Release Job
    @router.post(
        "/jobs/{job_id}/release",
        response_model=JobSpec,
        summary="Release hold on job",
    )
    def release_job(
        job_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> JobSpec:
        user_id, is_elevated = auth
        cmd = ReleaseJobCommand(job_id=job_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, cmd)

    # 5. Cancel Job
    @router.post(
        "/jobs/{job_id}/cancel",
        response_model=JobSpec,
        summary="Cancel individual job",
    )
    def cancel_job(
        job_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> JobSpec:
        user_id, is_elevated = auth
        cmd = CancelJobCommand(job_id=job_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, cmd)

    # 6. Explainability
    @router.get(
        "/jobs/{job_id}/explain",
        response_model=SchedulingDecisionReport,
        summary="Explain scheduling decision for job",
    )
    def explain_job(
        job_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> SchedulingDecisionReport:
        user_id, is_elevated = auth
        qry = ExplainJobQuery(
            job_id=job_id, requesting_user=user_id, is_admin=is_elevated
        )
        return _dispatch(pipeline, qry)

    # 7. Interactive PTY Session
    @router.post(
        "/jobs/{job_id}/pty",
        response_model=PtySessionInfo,
        summary="Create interactive PTY attach session",
    )
    def create_pty(
        job_id: str,
        cmd: CreatePtySessionCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> PtySessionInfo:
        user_id, is_elevated = auth
        effective_cmd = CreatePtySessionCommand(
            job_id=job_id,
            session_id=cmd.session_id or f"pty-{uuid4().hex[:8]}",
            command=cmd.command,
            user_id=user_id,
            elevate=is_elevated,
            rows=cmd.rows,
            cols=cmd.cols,
            term_type=cmd.term_type,
        )
        return _dispatch(pipeline, effective_cmd)

    return router


__all__ = [
    "create_jobs_router",
]
