"""Hexagonal architecture boundary tests for hexaqueue_core."""

from hexastack_core.testing import assert_clean_architecture


def test_hexaqueue_core_clean_architecture() -> None:
    """Assert hexaqueue_core strictly complies with Hexagonal layer isolation."""
    assert_clean_architecture("hexaqueue_core")
