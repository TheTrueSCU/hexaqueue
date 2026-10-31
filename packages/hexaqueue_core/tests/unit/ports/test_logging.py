"""Unit tests for logging port models and contracts."""

import inspect

import pytest

from hexaqueue_core.ports.logging import LogChunk, LogStreamPort


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


def test_log_stream_port_is_abstract() -> None:
    """Verify that LogStreamPort cannot be instantiated directly and is abstract."""
    is_abs = inspect.isabstract(LogStreamPort)
    assert is_abs is True
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        LogStreamPort()  # ty: ignore[call-non-callable] # type: ignore[abstract]


def test_log_stream_port_abstract_methods() -> None:
    """Verify abstract methods on LogStreamPort."""
    expected = {"close_stream", "stream_logs", "write_log"}
    abstracts = LogStreamPort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0
