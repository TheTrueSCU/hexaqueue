"""Pipeline DAG run and test suite execution REST API endpoints.

Notes/Architectural Intent:
    Orchestrates DAG submission, status polling, real-time SSE progress streaming,
    cancellation, and suite compilation dispatch into the unified execution pipeline.
"""

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
    status,
)
from fastapi.responses import StreamingResponse
from hexastack_cqrs.infra.pipeline import ExecutionPipeline
from hexastack_fastapi.adapters.dependencies import get_pipeline

from hexaqueue_core.domain.cqrs import (
    CancelRunCommand,
    GetRunStatusQuery,
    SubmitRunCommand,
    SubmitSuiteCommand,
)
from hexaqueue_server.adapters.api.auth import get_auth_context
from hexaqueue_server.adapters.api.common import (
    _dispatch,
    _generate_run_status_events,
)
from hexaqueue_server.domain.models import RunStatusReport


def create_runs_router() -> APIRouter:
    """Construct APIRouter for pipeline run and test suite operations.

    Returns:
        APIRouter with endpoints for run submission, status, streaming, and cancellation.
    """
    router = APIRouter()

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
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> RunStatusReport:
        user_id, is_elevated = auth
        effective_cmd = SubmitRunCommand(
            run_spec=cmd.run_spec,
            jobs=cmd.jobs,
            dependencies=cmd.dependencies,
            user_id=user_id,
            elevate=is_elevated,
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
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> RunStatusReport:
        user_id, is_elevated = auth
        qry = GetRunStatusQuery(run_id=run_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, qry)

    # 3. Stream Run Status (SSE)
    @router.get(
        "/runs/{run_id}/stream",
        summary="Stream pipeline DAG run progress via Server-Sent Events",
        response_class=StreamingResponse,
    )
    async def stream_run_status(
        run_id: str,
        request: Request,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
        poll_interval: Annotated[float, Query(ge=0.05, le=5.0)] = 0.25,
        max_events: Annotated[int | None, Query(ge=1)] = None,
        timeout: Annotated[float | None, Query(ge=0.1, le=3600.0)] = None,
    ) -> StreamingResponse:
        """Stream run status snapshots as Server-Sent Events (SSE).

        Args:
            run_id: Root pipeline run identifier.
            request: Active FastAPI HTTP request for client disconnect detection.
            pipeline: CQRS execution pipeline.
            auth: Resolved authentication tuple (user_id, is_elevated).
            poll_interval: Interval between status polls in seconds.
            max_events: Optional maximum number of events to emit before closing stream.
            timeout: Optional maximum duration in seconds before terminating stream.

        Returns:
            StreamingResponse emitting SSE text/event-stream pulses.
        """
        user_id, is_elevated = auth
        events = _generate_run_status_events(
            request=request,
            pipeline=pipeline,
            run_id=run_id,
            user_id=user_id,
            is_elevated=is_elevated,
            poll_interval=poll_interval,
            max_events=max_events,
            timeout=timeout,
        )
        return StreamingResponse(
            events,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # 4. Cancel Run
    @router.post(
        "/runs/{run_id}/cancel",
        response_model=RunStatusReport,
        summary="Cancel pipeline run",
    )
    def cancel_run(
        run_id: str,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> RunStatusReport:
        user_id, is_elevated = auth
        cmd = CancelRunCommand(run_id=run_id, user_id=user_id, elevate=is_elevated)
        return _dispatch(pipeline, cmd)

    # 5. Suite Submission
    @router.post(
        "/suites",
        response_model=RunStatusReport,
        status_code=status.HTTP_201_CREATED,
        summary="Submit hierarchical suite workload",
    )
    def submit_suite(
        cmd: SubmitSuiteCommand,
        pipeline: Annotated[ExecutionPipeline, Depends(get_pipeline)],
        auth: Annotated[tuple[str, bool], Depends(get_auth_context)],
    ) -> RunStatusReport:
        user_id, is_elevated = auth
        effective_cmd = SubmitSuiteCommand(
            suite_spec=cmd.suite_spec,
            user_id=user_id,
            elevate=is_elevated,
        )
        return _dispatch(pipeline, effective_cmd)

    return router


__all__ = [
    "create_runs_router",
]
