"""Tests for hexaqueue_server.infra exports."""

from hexaqueue_server import infra


def test_infra_exports() -> None:
    """Verify infra package exports."""
    assert hasattr(infra, "ServerBootstrapper")
