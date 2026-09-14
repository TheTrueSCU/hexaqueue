"""Hexagonal architecture boundary tests for hexaqueue_kueue."""

from hexastack_core.testing import assert_clean_architecture


def test_hexaqueue_kueue_clean_architecture() -> None:
    """Assert hexaqueue_kueue strictly complies with Hexagonal layer isolation."""
    assert_clean_architecture("hexaqueue_kueue")
