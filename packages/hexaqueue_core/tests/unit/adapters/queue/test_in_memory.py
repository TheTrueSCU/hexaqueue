"""Unit tests for in-memory job queue adapter."""

import pytest

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.job import JobSpec


@pytest.mark.asyncio
async def test_in_memory_job_queue():
    """Verify FIFO queue ordering, dequeue, and peek operations."""
    queue = InMemoryJobQueueAdapter()
    assert await queue.size() == 0

    job_1 = JobSpec(
        id="job-1",
        run_id="run-1",
        name="job-first",
        command="echo first",
    )
    job_2 = JobSpec(
        id="job-2",
        run_id="run-1",
        name="job-second",
        command="echo second",
    )

    await queue.enqueue(job_1)
    await queue.enqueue(job_2)

    assert await queue.size() == 2
    peeked = await queue.peek(limit=5)
    assert len(peeked) == 2
    assert peeked[0].id == "job-1"

    dequeued_1 = await queue.dequeue()
    assert dequeued_1 is not None and dequeued_1.id == "job-1"

    dequeued_2 = await queue.dequeue()
    assert dequeued_2 is not None and dequeued_2.id == "job-2"

    assert await queue.dequeue() is None


@pytest.mark.asyncio
async def test_in_memory_job_queue_remove():
    """Verify job removal from queue."""
    queue = InMemoryJobQueueAdapter()
    job = JobSpec(id="job-rm", run_id="run-1", name="to-remove", command="echo 1")
    await queue.enqueue(job)
    assert await queue.size() == 1

    removed = await queue.remove("job-rm")
    assert removed is True
    assert await queue.size() == 0

    not_removed = await queue.remove("job-non-existent")
    assert not_removed is False
