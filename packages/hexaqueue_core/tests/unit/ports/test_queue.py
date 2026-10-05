"""Tests for JobQueuePort interface."""

import pytest

from hexaqueue_core.ports.queue import JobQueuePort


def test_job_queue_port_is_abstract() -> None:
    """Verify JobQueuePort cannot be instantiated directly."""
    with pytest.raises(TypeError):
        JobQueuePort()  # type: ignore[abstract]
