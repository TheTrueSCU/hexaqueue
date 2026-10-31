"""Unit tests for in-memory scan task queue adapter."""

import pytest

from hexaqueue_scanner.adapters.queue import InMemoryScanTaskQueueAdapter


@pytest.mark.asyncio
async def test_in_memory_queue_operations() -> None:
    """Verify queue enqueue, dequeue, and size calculations."""
    queue = InMemoryScanTaskQueueAdapter()
    init_size = queue.queue_size()
    assert init_size == 0

    await queue.enqueue_task("col-001")
    await queue.enqueue_task("col-002")

    size = queue.queue_size()
    assert size == 2

    task1 = await queue.get_next_task(timeout_seconds=0.1)
    assert task1 == "col-001"

    task2 = await queue.get_next_task(timeout_seconds=0.1)
    assert task2 == "col-002"

    task_none = await queue.get_next_task(timeout_seconds=0.01)
    assert task_none is None
