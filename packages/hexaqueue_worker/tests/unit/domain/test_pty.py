"""Unit tests for PTY domain models."""

import pytest

from hexaqueue_worker.domain.pty import (
    PtyResizeEvent,
    PtySessionInfo,
    PtySessionRequest,
)


def test_pty_session_request_valid() -> None:
    """Verify PtySessionRequest instantiation and defaults."""
    req = PtySessionRequest(
        session_id="sess-01",
        job_id="job-123",
        user_id="alice",
        roles=["developer"],
        command=["/bin/sh"],
        rows=30,
        cols=100,
    )
    s_id = req.session_id
    assert s_id == "sess-01"
    j_id = req.job_id
    assert j_id == "job-123"
    u_id = req.user_id
    assert u_id == "alice"
    rows = req.rows
    assert rows == 30
    cols = req.cols
    assert cols == 100


def test_pty_session_request_empty_fields() -> None:
    """Verify empty identifiers raise ValueError."""
    with pytest.raises(ValueError, match="session_id cannot be empty"):
        PtySessionRequest(session_id="", job_id="job-1", user_id="alice")

    with pytest.raises(ValueError, match="job_id cannot be empty"):
        PtySessionRequest(session_id="sess-1", job_id="", user_id="alice")

    with pytest.raises(ValueError, match="user_id cannot be empty"):
        PtySessionRequest(session_id="sess-1", job_id="job-1", user_id="")

    with pytest.raises(ValueError, match="command vector cannot be empty"):
        PtySessionRequest(
            session_id="sess-1", job_id="job-1", user_id="alice", command=[]
        )


def test_pty_resize_event_and_info() -> None:
    """Verify PtyResizeEvent and PtySessionInfo instantiation."""
    ev = PtyResizeEvent(session_id="sess-01", rows=40, cols=120)
    assert ev.rows == 40
    assert ev.cols == 120

    info = PtySessionInfo(
        session_id="sess-01",
        job_id="job-123",
        user_id="alice",
        pid=12345,
        is_active=True,
    )
    assert info.pid == 12345
    assert info.is_active is True
