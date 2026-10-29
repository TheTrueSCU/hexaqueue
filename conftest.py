"""Root conftest.py for the Hexaqueue monorepo test suite.

Notes/Architectural Intent:
    Provides monorepo-wide pytest configuration and deterministic test fixtures.
    Enforces hermetic execution environments by clearing ambient telemetry
    variables (Sentry) and resetting ambient context variables across xdist workers.
"""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom monorepo-wide pytest markers.

    Args:
        config: The active pytest configuration object.

    Notes/Architectural Intent:
        Monorepo markers are registered at root level to prevent
        PytestUnknownMarkWarning warnings across workspace test suites.
    """
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
    """Deterministically seeded Faker instance across test runs.

    Notes/Architectural Intent:
        Guarantees 100% reproducible synthetic data generation compatible
        with snapshot testing and deterministic CI runs.
    """
    from hexastack_core.testing.synthetic import seeded_faker

    return seeded_faker(seed=42)


@pytest.fixture(autouse=True)
def _reset_hermetic_contextvars():
    """Ensure contextvars are reset to default state across test invocations.

    Notes/Architectural Intent:
        Guarantees hermetic test isolation across parallel xdist workers
        preventing leaked user_ctx or correlation_id_ctx from cascading.
    """
    from hexastack_core.utils.context import correlation_id_ctx, user_ctx

    token_cid = correlation_id_ctx.set("")
    token_user = user_ctx.set(None)
    try:
        yield
    finally:
        correlation_id_ctx.reset(token_cid)
        user_ctx.reset(token_user)


@pytest.fixture(autouse=True)
def _isolate_hermetic_sentry_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure SENTRY_DSN is cleared by default to prevent tests from leaking live network calls.

    Notes/Architectural Intent:
        Prevents ambient environment variables from .env or developer workstations from
        accidentally routing test exceptions to live Sentry ingest endpoints. Individual
        tests that verify Sentry configuration can still explicitly override SENTRY_DSN.
    """
    monkeypatch.setenv("SENTRY_DSN", "")
