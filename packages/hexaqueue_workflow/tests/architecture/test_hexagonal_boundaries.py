"""Hexagonal architecture boundary tests for hexaqueue_workflow."""

from hexastack_core.testing import assert_clean_architecture


def test_hexaqueue_workflow_clean_architecture() -> None:
    """Assert hexaqueue_workflow strictly complies with Hexagonal layer isolation."""
    assert_clean_architecture("hexaqueue_workflow")
