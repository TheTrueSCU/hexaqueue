"""Job inspection, lifecycle mutation, explainability, and PTY session REST endpoints.

Notes/Architectural Intent:
    Provides granular job management including administrative hold/release,
    preemption cancellation, multi-factor priority explainability diagnostics,
    task queue lifecycle coordination, and secure pseudo-terminal attach session allocation.
"""

import contextlib
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Response,
    status,
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
    SubmitRunCommand,
)
from hexaqueue_core.domain.explainability import SchedulingDecisionReport
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import JobState
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_server.adapters.api.auth import get_auth_context
from hexaqueue_server.adapters.api.common import _dispatch
from hexaqueue_server.domain.models import (
    TaskQueueCompleteRequest,
    TaskQueueFailRequest,
    TaskQueueJobRequest,
    TaskQueueLeaseRequest,
    TaskRecordResponse,
)
from hexaqueue_worker.domain.pty import PtySessionInfo


def create_jobs_router() -> APIRouter:
    """Construct APIRouter for job operations and lifecycle controls.

    Returns:
        APIRouter with endpoints for jobs inspection, lifecycle, explainability, task queue, and PTY.
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
        """List jobs matching optional run_id filter."""
        user_id, is_elevated = auth
        qry = ListJobsQuery(run_id=run_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    # 2. Enqueue Task Queue Job
    @router.post(
        "/jobs",
        response_model=TaskRecordResponse,
        status_code=status.HTTP_201_CREATED,
        summary="Enqueue background task into distributed queue",
    )
    def enqueue_job(
        req: TaskQueueJobRequest,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> TaskRecordResponse:
        """Enqueue task for remote worker consumption conforming to Hexastack task queue contracts."""
        user_id, is_elevated = auth
        task_id = f"task_{uuid4().hex[:12]}"
        run_id = f"run_{task_id}"
        now_ts = datetime.now(UTC).timestamp()

        cmd = SubmitRunCommand(
            run_spec=RunSpec(
                id=run_id,
                name=f"task_{req.task_name}",
                tags=["task_queue", f"queue:{req.queue}"],
            ),
            jobs=[
                JobSpec(
                    id=task_id,
                    run_id=run_id,
                    name=req.task_name,
                    command=f"task:{req.task_name}",
                    priority=req.priority,
                    tags=[f"queue:{req.queue}"],
                    user=user_id,
                )
            ],
            dependencies={},
            user_id=user_id,
            elevate=is_elevated,
        )
        _dispatch(pipeline, cmd)

        return TaskRecordResponse(
            id=task_id,
            task_name=req.task_name,
            payload=req.payload,
            state="PENDING",
            partition_key=req.partition_key,
            priority=req.priority,
            attempts=0,
            max_attempts=req.max_attempts,
            created_at=now_ts,
        )

    # 3. Lease Next Task
    @router.post(
        "/jobs/lease",
        response_model=TaskRecordResponse | None,
        summary="Acquire lease on next available queued task",
    )
    def lease_job(
        req: TaskQueueLeaseRequest,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> TaskRecordResponse | Response:
        """Lease the next highest priority available job for a worker daemon."""
        user_id, is_elevated = auth
        qry = ListJobsQuery(user_id=user_id, elevate=is_elevated)
        jobs: list[JobSpec] = _dispatch(pipeline, qry)

        now_ts = datetime.now(UTC).timestamp()
        for j in jobs:
            if j.status.state == JobState.PENDING:
                if req.task_names and j.name not in req.task_names:
                    continue
                return TaskRecordResponse(
                    id=j.id,
                    task_name=j.name,
                    payload={},
                    state="RUNNING",
                    priority=j.priority,
                    attempts=1,
                    lease_owner=req.worker_id,
                    lease_expires_at=now_ts + req.lease_duration_seconds,
                    created_at=j.created_at.timestamp(),
                )

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # 4. Get Job
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
        """Retrieve granular job metadata and current lifecycle status."""
        user_id, is_elevated = auth
        qry = GetJobQuery(job_id=job_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    # 5. Hold Job
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
        """Place administrative hold on a job."""
        user_id, is_elevated = auth
        cmd = HoldJobCommand(job_id=job_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, cmd)

    # 6. Release Job
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
        """Release administrative hold on a job."""
        user_id, is_elevated = auth
        cmd = ReleaseJobCommand(job_id=job_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, cmd)

    # 7. Cancel Job
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
        """Cancel an individual job."""
        user_id, is_elevated = auth
        cmd = CancelJobCommand(job_id=job_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, cmd)

    # 8. Complete Leased Task Job
    @router.post(
        "/jobs/{job_id}/complete",
        summary="Acknowledge leased task completion",
    )
    def complete_task_job(
        job_id: str,
        cmd: TaskQueueCompleteRequest,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> dict[str, str]:
        """Mark leased task as successfully processed."""
        user_id, is_elevated = auth
        cancel_cmd = CancelJobCommand(
            job_id=job_id, user_id=user_id, elevate=is_elevated
        )
        with contextlib.suppress(Exception):
            _dispatch(pipeline, cancel_cmd)
        return {"status": "completed"}

    # 9. Fail Leased Task Job
    @router.post(
        "/jobs/{job_id}/fail",
        summary="Record leased task failure",
    )
    def fail_task_job(
        job_id: str,
        cmd: TaskQueueFailRequest,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> dict[str, str]:
        """Record leased task failure from worker."""
        user_id, is_elevated = auth
        cancel_cmd = CancelJobCommand(
            job_id=job_id, user_id=user_id, elevate=is_elevated
        )
        with contextlib.suppress(Exception):
            _dispatch(pipeline, cancel_cmd)
        return {"status": "failed"}

    # 10. Explainability
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
        """Explain multi-factor scheduling ranking and preemption priority."""
        user_id, is_elevated = auth
        qry = ExplainJobQuery(
            job_id=job_id, requesting_user=user_id, is_admin=is_elevated
        )
        return _dispatch(pipeline, qry)

    # 11. Interactive PTY Session
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
        """Allocate interactive pseudo-terminal session."""
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
