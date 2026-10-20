"""Tests for JobQueuePort interface."""

import inspect

from hexaqueue_core.ports.queue import JobQueuePort


def test_job_queue_port_is_abstract() -> None:
    """Verify JobQueuePort is an abstract interface."""
    assert inspect.isabstract(JobQueuePort)
    assert "enqueue" in JobQueuePort.__abstractmethods__
    assert "dequeue" in JobQueuePort.__abstractmethods__
