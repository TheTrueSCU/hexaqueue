"""Tests for hexaqueue_server.ports exports."""

from hexaqueue_server import ports


def test_ports_exports() -> None:
    """Verify ports package exports."""
    assert hasattr(ports, "SchedulerControllerPort")
