"""Hexagonal architecture boundary tests for hexaqueue_dashboard."""

from hexastack_core.testing import assert_clean_architecture


def test_hexaqueue_dashboard_clean_architecture() -> None:
    """Assert hexaqueue_dashboard strictly complies with Hexagonal layer isolation."""
    assert_clean_architecture("hexaqueue_dashboard")
