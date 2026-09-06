"""Test adapters exports."""

from monte_carlo.adapters.local import LocalMonteCarloEngine


def test_adapters_exports() -> None:
    """Verify adapters implementations are available."""
    assert LocalMonteCarloEngine is not None
