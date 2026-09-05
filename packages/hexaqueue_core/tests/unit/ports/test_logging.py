"""Unit tests for logging port models and contracts."""

import pytest

from hexaqueue_core.ports.logging import LogChunk


def test_log_chunk_valid():
    """Verify LogChunk creation and fields."""
    chunk = LogChunk(
        job_id="job-1",
        stream="stdout",
        content="Task started\n",
        offset=0,
    )
    assert chunk.job_id == "job-1"
    assert chunk.stream == "stdout"
    assert chunk.content == "Task started\n"


def test_log_chunk_invalid_invariants():
    """Verify LogChunk rejects invalid job_id or stream types."""
    with pytest.raises(ValueError, match="job_id cannot be empty"):
        LogChunk(job_id="", stream="stdout", content="test", offset=0)

    with pytest.raises(
        ValueError, match="stream must be 'stdout', 'stderr', or 'system'"
    ):
        LogChunk(job_id="job-1", stream="invalid_stream", content="test", offset=0)
