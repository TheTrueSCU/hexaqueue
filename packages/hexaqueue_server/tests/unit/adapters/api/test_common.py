"""Tests for common dispatch and SSE streaming helpers in api package."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from hexastack_cqrs.infra.pipeline import ExecutionPipeline

from hexaqueue_core.domain.exceptions import (
    HexaqueueError,
    PermissionDeniedError,
)
from hexaqueue_core.domain.lifecycle import RunState
from hexaqueue_server.adapters.api.common import (
    _dispatch,
    _generate_run_status_events,
)
from hexaqueue_server.domain.models import RunStatusReport


def test_dispatch_success() -> None:
    """Verify _dispatch executes message and returns result."""
    pipeline = MagicMock(spec=ExecutionPipeline)
    pipeline.execute.return_value = {"ok": True}
    res = _dispatch(pipeline, "dummy-msg")
    assert res == {"ok": True}


def test_dispatch_permission_denied_mapping() -> None:
    """Verify PermissionDeniedError is translated to HTTP 403."""
    pipeline = MagicMock(spec=ExecutionPipeline)
    pipeline.execute.side_effect = PermissionDeniedError("Forbidden operation")
    with pytest.raises(HTTPException) as exc_info:
        _dispatch(pipeline, "dummy-msg")
    code = exc_info.value.status_code
    assert code == 403


def test_dispatch_hexaqueue_error_mapping() -> None:
    """Verify HexaqueueError is translated to HTTP 400."""
    pipeline = MagicMock(spec=ExecutionPipeline)
    pipeline.execute.side_effect = HexaqueueError("Bad request")
    with pytest.raises(HTTPException) as exc_info:
        _dispatch(pipeline, "dummy-msg")
    code = exc_info.value.status_code
    assert code == 400


@pytest.mark.asyncio
async def test_generate_run_status_events_stream() -> None:
    """Verify SSE generator emits run status and terminates on DONE state."""
    from datetime import UTC, datetime

    mock_request = MagicMock()
    mock_request.is_disconnected = AsyncMock(return_value=False)

    report_done = RunStatusReport(
        completed_jobs=1,
        created_at=datetime.now(UTC),
        failed_jobs=0,
        pending_jobs=0,
        run_id="run-1",
        running_jobs=0,
        state=RunState.DONE,
        total_jobs=1,
    )
    pipeline = MagicMock(spec=ExecutionPipeline)
    pipeline.execute.return_value = report_done

    events = [
        event
        async for event in _generate_run_status_events(
            request=mock_request,
            pipeline=pipeline,
            run_id="run-1",
            user_id="default",
            is_elevated=False,
            poll_interval=0.01,
            max_events=2,
            timeout=1.0,
        )
    ]
    event_cnt = len(events)
    assert event_cnt >= 1
    assert any("event: run_status" in e for e in events)
