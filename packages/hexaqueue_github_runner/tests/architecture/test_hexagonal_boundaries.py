"""Hexagonal architecture boundary tests for hexaqueue_github_runner."""

from hexastack_core.testing import assert_clean_architecture


def test_hexaqueue_github_runner_clean_architecture() -> None:
    """Assert hexaqueue_github_runner strictly complies with Hexagonal layer isolation."""
    assert_clean_architecture("hexaqueue_github_runner")
