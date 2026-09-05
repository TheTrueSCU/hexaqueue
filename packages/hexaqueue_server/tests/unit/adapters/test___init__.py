"""Tests for hexaqueue_server.adapters exports."""

from hexaqueue_server import adapters


def test_adapters_exports() -> None:
    """Verify adapters package exports."""
    assert hasattr(adapters, "LocalSchedulerControllerAdapter")
