"""Unit tests for BatchSchedulerPort interface."""

import inspect

from hexaqueue_core.ports.scheduling import BatchSchedulerPort


def test_batch_scheduler_port_is_abstract() -> None:
    """Verify BatchSchedulerPort is an abstract interface."""
    assert inspect.isabstract(BatchSchedulerPort)
    assert "schedule_cycle" in BatchSchedulerPort.__abstractmethods__
