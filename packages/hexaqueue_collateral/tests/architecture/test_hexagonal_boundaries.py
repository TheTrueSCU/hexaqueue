"""Hexagonal architecture boundary tests for hexaqueue_collateral."""

from hexastack_core.testing import assert_clean_architecture


def test_hexaqueue_collateral_clean_architecture() -> None:
    """Assert hexaqueue_collateral strictly complies with Hexagonal layer isolation."""
    assert_clean_architecture("hexaqueue_collateral")
