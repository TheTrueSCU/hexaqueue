"""Root conftest.py for the Hexaqueue monorepo test suite.

Notes/Architectural Intent:
    Provides monorepo-wide pytest configuration and deterministic test fixtures.
"""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom monorepo-wide pytest markers."""
    config.addinivalue_line(
        "markers",
        "integration: mark a test as requiring external infrastructure.",
    )
    config.addinivalue_line(
        "markers",
        "slow: mark a test as slow-running.",
    )


@pytest.fixture
def fake():
    """Deterministically seeded Faker instance across test runs."""
    from faker import Faker

    faker = Faker()
    faker.seed_instance(42)
    return faker
