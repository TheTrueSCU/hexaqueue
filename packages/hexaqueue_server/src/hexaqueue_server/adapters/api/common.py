"""Common dispatch and streaming helpers for Hexaqueue REST presentation adapters.

Notes/Architectural Intent:
    Decouples CQRS execution pipeline invocation and error mapping from route handlers,
    translating domain exceptions into standardized HTTP error responses.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException, Request, status
from hexastack_cqrs.infra.pipeline import ExecutionPipeline

from hexaqueue_core.domain.cqrs import GetRunStatusQuery
from hexaqueue_core.domain.exceptions import (
    HexaqueueError,
    PermissionDeniedError,
)
from hexaqueue_core.domain.lifecycle import RunState
from hexaqueue_server.domain.models import RunStatusReport


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


async def _generate_run_status_events(
    request: Request,
    pipeline: ExecutionPipeline,
    run_id: str,
    user_id: str,
    is_elevated: bool,
    poll_interval: float,
    max_events: int | None,
    timeout: float | None,
) -> AsyncIterator[str]:
    """Generate Server-Sent Events for run status progression until completion or termination.

    Args:
        request: FastAPI HTTP request to monitor client disconnects.
        pipeline: CQRS execution pipeline.
        run_id: Target pipeline run identifier.
        user_id: Requesting user identity.
        is_elevated: Whether elevation is active.
        poll_interval: Poll frequency in seconds.
        max_events: Optional maximum events count before closing.
        timeout: Optional duration timeout in seconds.

    Yields:
        SSE text/event-stream chunks.
    """
    last_state = None
    last_completed = -1
    last_failed = -1
    last_running = -1
    events_sent = 0
    start_time = time.monotonic()
    while True:
        if await request.is_disconnected():
            break
        if max_events is not None and events_sent >= max_events:
            break
        if timeout is not None and (time.monotonic() - start_time) >= timeout:
            break

        try:
            qry = GetRunStatusQuery(run_id=run_id, user_id=user_id, elevate=is_elevated)
            status_report: RunStatusReport = _dispatch(pipeline, qry)
        except Exception:
            yield 'event: error\ndata: {"error": "Failed to retrieve run status"}\n\n'
            break

        is_progress = (
            status_report.state != last_state
            or status_report.completed_jobs != last_completed
            or status_report.failed_jobs != last_failed
            or status_report.running_jobs != last_running
        )
        if is_progress:
            last_state = status_report.state
            last_completed = status_report.completed_jobs
            last_failed = status_report.failed_jobs
            last_running = status_report.running_jobs
            yield f"event: run_status\ndata: {status_report.model_dump_json()}\n\n"
            events_sent += 1

        is_terminal = status_report.state == RunState.DONE or (
            status_report.state == RunState.BLOCKED
            and status_report.running_jobs == 0
            and status_report.failed_jobs > 0
            and status_report.outcome is not None
        )
        if is_terminal:
            if max_events is None or events_sent < max_events:
                yield f"event: run_done\ndata: {status_report.model_dump_json()}\n\n"
            break

        if max_events is not None and events_sent >= max_events:
            break

        await asyncio.sleep(poll_interval)


__all__ = [
    "_dispatch",
    "_generate_run_status_events",
]
