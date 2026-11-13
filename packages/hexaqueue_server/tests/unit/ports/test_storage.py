"""Unit tests for SchedulerStoragePort interface."""

import inspect

from hexaqueue_server.ports.storage import SchedulerStoragePort


def test_scheduler_storage_port_is_abstract() -> None:
    """Verify SchedulerStoragePort is an abstract interface."""
    assert inspect.isabstract(SchedulerStoragePort)
    assert "record_run" in SchedulerStoragePort.__abstractmethods__
    assert "get_run" in SchedulerStoragePort.__abstractmethods__
    assert "list_runs" in SchedulerStoragePort.__abstractmethods__
    assert "record_job" in SchedulerStoragePort.__abstractmethods__
    assert "get_job" in SchedulerStoragePort.__abstractmethods__
    assert "list_jobs" in SchedulerStoragePort.__abstractmethods__
    assert "record_node" in SchedulerStoragePort.__abstractmethods__
    assert "get_node" in SchedulerStoragePort.__abstractmethods__
    assert "list_nodes" in SchedulerStoragePort.__abstractmethods__
    assert "record_telemetry_pulse" in SchedulerStoragePort.__abstractmethods__
    assert "list_telemetry_pulses" in SchedulerStoragePort.__abstractmethods__
    assert "flush" in SchedulerStoragePort.__abstractmethods__
    assert "close" in SchedulerStoragePort.__abstractmethods__
