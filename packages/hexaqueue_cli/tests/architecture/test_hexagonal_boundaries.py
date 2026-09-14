"""Hexagonal architecture boundary tests for hexaqueue_cli."""

from hexastack_core.testing import assert_clean_architecture


def test_hexaqueue_cli_clean_architecture() -> None:
    """Assert hexaqueue_cli strictly complies with Hexagonal layer isolation."""
    assert_clean_architecture("hexaqueue_cli")
