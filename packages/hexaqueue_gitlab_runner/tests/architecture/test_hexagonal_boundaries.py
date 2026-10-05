"""Hexagonal architecture boundary tests for hexaqueue_gitlab_runner."""

from hexastack_core.testing import assert_clean_architecture


def test_hexaqueue_gitlab_runner_clean_architecture() -> None:
    """Assert hexaqueue_gitlab_runner strictly complies with Hexagonal layer isolation."""
    assert_clean_architecture("hexaqueue_gitlab_runner")
