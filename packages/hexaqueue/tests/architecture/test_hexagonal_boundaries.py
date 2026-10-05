"""Hexagonal architecture boundary tests for hexaqueue."""

from hexastack_core.testing import assert_clean_architecture


def test_hexaqueue_clean_architecture() -> None:
    """Assert hexaqueue strictly complies with Hexagonal layer isolation."""
    assert_clean_architecture("hexaqueue")
