"""Unit tests for BatchSchedulerPort interface."""

import pytest

from hexaqueue_core.ports.scheduling import BatchSchedulerPort


def test_batch_scheduler_port_is_abstract() -> None:
    """Verify BatchSchedulerPort cannot be instantiated directly."""
    with pytest.raises(TypeError):
        BatchSchedulerPort()  # type: ignore[abstract]
