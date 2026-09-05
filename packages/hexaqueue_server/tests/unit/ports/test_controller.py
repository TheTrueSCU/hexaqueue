"""Tests for SchedulerControllerPort interface."""

import pytest

from hexaqueue_server.ports.controller import SchedulerControllerPort


def test_scheduler_controller_port_is_abstract() -> None:
    """Verify SchedulerControllerPort cannot be instantiated directly."""
    with pytest.raises(TypeError):
        SchedulerControllerPort()  # type: ignore[abstract]
