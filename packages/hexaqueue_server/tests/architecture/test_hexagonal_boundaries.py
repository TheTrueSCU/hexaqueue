"""Hexagonal architecture boundary tests for hexaqueue_server."""

from hexastack_core.testing import assert_clean_architecture


def test_hexaqueue_server_clean_architecture() -> None:
    """Assert hexaqueue_server strictly complies with Hexagonal layer isolation."""
    assert_clean_architecture("hexaqueue_server")
