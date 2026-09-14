"""Hexagonal architecture boundary tests for hexaqueue_scanner."""

from hexastack_core.testing import assert_clean_architecture


def test_hexaqueue_scanner_clean_architecture() -> None:
    """Assert hexaqueue_scanner strictly complies with Hexagonal layer isolation."""
    assert_clean_architecture("hexaqueue_scanner")
