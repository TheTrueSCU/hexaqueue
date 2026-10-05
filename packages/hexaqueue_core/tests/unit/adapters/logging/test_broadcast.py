"""Unit tests for BroadcastLogStreamAdapter."""

import asyncio

import pytest

from hexaqueue_core.adapters.logging.broadcast import BroadcastLogStreamAdapter
from hexaqueue_core.ports.logging import LogChunk


@pytest.mark.asyncio
async def test_broadcast_historical_buffering() -> None:
    """Verify log chunk appending and retrieval with tail."""
    log_port = BroadcastLogStreamAdapter(history_limit=10)
    await log_port.write_log(
        LogChunk(job_id="job-1", stream="stdout", content="line 1\n", offset=0)
    )
    await log_port.write_log(
        LogChunk(job_id="job-1", stream="stdout", content="line 2\n", offset=1)
    )

    chunks = [c async for c in log_port.stream_logs("job-1")]
    chunks_len = len(chunks)
    assert chunks_len == 2
    assert chunks[0].content == "line 1\n"
    assert chunks[1].content == "line 2\n"

    tail_chunks = [c async for c in log_port.stream_logs("job-1", tail=1)]
    tail_len = len(tail_chunks)
    assert tail_len == 1
    assert tail_chunks[0].content == "line 2\n"


@pytest.mark.asyncio
async def test_broadcast_live_streaming() -> None:
    """Verify live subscription receives incoming chunks and terminates on close."""
    log_port = BroadcastLogStreamAdapter()
    received: list[LogChunk] = []

    async def _subscriber() -> None:
        async for chunk in log_port.stream_logs("job-live", follow=True):
            received.append(chunk)

    sub_task = asyncio.create_task(_subscriber())
    await asyncio.sleep(0.01)

    await log_port.write_log(
        LogChunk(job_id="job-live", stream="stdout", content="first\n", offset=0)
    )
    await log_port.write_log(
        LogChunk(job_id="job-live", stream="stderr", content="warn\n", offset=1)
    )
    await asyncio.sleep(0.01)

    await log_port.close_stream("job-live")
    await sub_task

    rec_len = len(received)
    assert rec_len == 2
    assert received[0].content == "first\n"
    assert received[1].content == "warn\n"


@pytest.mark.asyncio
async def test_broadcast_multiple_subscribers() -> None:
    """Verify multiple concurrent subscribers receive broadcast chunks."""
    log_port = BroadcastLogStreamAdapter()
    sub1_chunks: list[LogChunk] = []
    sub2_chunks: list[LogChunk] = []

    async def _sub(dest: list[LogChunk]) -> None:
        async for chunk in log_port.stream_logs("job-multi", follow=True):
            dest.append(chunk)

    t1 = asyncio.create_task(_sub(sub1_chunks))
    t2 = asyncio.create_task(_sub(sub2_chunks))
    await asyncio.sleep(0.01)

    await log_port.write_log(
        LogChunk(job_id="job-multi", stream="stdout", content="broadcast\n", offset=0)
    )
    await asyncio.sleep(0.01)

    await log_port.close_stream("job-multi")
    await asyncio.gather(t1, t2)

    assert len(sub1_chunks) == 1
    assert len(sub2_chunks) == 1
    assert sub1_chunks[0].content == "broadcast\n"
    assert sub2_chunks[0].content == "broadcast\n"


@pytest.mark.asyncio
async def test_broadcast_already_closed_stream() -> None:
    """Verify stream_logs with follow=True on already closed job returns history immediately."""
    log_port = BroadcastLogStreamAdapter()
    await log_port.write_log(
        LogChunk(job_id="job-done", stream="stdout", content="done\n", offset=0)
    )
    await log_port.close_stream("job-done")

    chunks = [c async for c in log_port.stream_logs("job-done", follow=True)]
    chunks_len = len(chunks)
    assert chunks_len == 1
    assert chunks[0].content == "done\n"


@pytest.mark.asyncio
async def test_broadcast_queue_overflow_discard() -> None:
    """Verify slow subscriber queue drops chunks gracefully without blocking write_log."""
    log_port = BroadcastLogStreamAdapter(subscriber_queue_size=2)

    # Register subscriber but never drain it
    gen = log_port.stream_logs("job-overflow", follow=True)

    async def _fetch_first() -> LogChunk:
        return await anext(gen)

    init_task = asyncio.create_task(_fetch_first())
    await asyncio.sleep(0.01)

    for i in range(10):
        await log_port.write_log(
            LogChunk(
                job_id="job-overflow",
                stream="stdout",
                content=f"msg {i}\n",
                offset=i,
            )
        )

    await log_port.close_stream("job-overflow")
    first_chunk = await init_task
    assert first_chunk.job_id == "job-overflow"
