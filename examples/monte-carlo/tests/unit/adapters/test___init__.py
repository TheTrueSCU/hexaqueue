"""Test adapters exports."""

import monte_carlo.adapters


def test_adapters_exports() -> None:
    """Verify adapters __all__."""
    assert hasattr(monte_carlo.adapters, "LocalMonteCarloEngine")
