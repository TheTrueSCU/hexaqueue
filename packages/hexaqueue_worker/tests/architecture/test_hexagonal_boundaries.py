"""Hexagonal architecture boundary tests for hexaqueue_worker."""

from hexastack_core.testing import assert_clean_architecture


def test_hexaqueue_worker_clean_architecture() -> None:
    """Assert hexaqueue_worker strictly complies with Hexagonal layer isolation."""
    assert_clean_architecture("hexaqueue_worker")
