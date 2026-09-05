"""Unit tests for in-memory log stream adapter."""

import pytest

from hexaqueue_core.adapters.logging.in_memory import InMemoryLogStreamAdapter
from hexaqueue_core.ports.logging import LogChunk


@pytest.mark.asyncio
async def test_in_memory_log_stream():
    """Verify log chunk appending and retrieval with tail."""
    log_port = InMemoryLogStreamAdapter()
    await log_port.write_log(
        LogChunk(job_id="job-1", stream="stdout", content="line 1\n", offset=0)
    )
    await log_port.write_log(
        LogChunk(job_id="job-1", stream="stdout", content="line 2\n", offset=1)
    )

    chunks = [c async for c in log_port.stream_logs("job-1")]
    assert len(chunks) == 2
    assert chunks[0].content == "line 1\n"
    assert chunks[1].content == "line 2\n"

    tail_chunks = [c async for c in log_port.stream_logs("job-1", tail=1)]
    assert len(tail_chunks) == 1
    assert tail_chunks[0].content == "line 2\n"
