"""Hexagonal architecture boundary tests for pytest_hexaqueue."""

from hexastack_core.testing import assert_clean_architecture


def test_pytest_hexaqueue_clean_architecture() -> None:
    """Assert pytest_hexaqueue strictly complies with Hexagonal layer isolation."""
    assert_clean_architecture("pytest_hexaqueue")
