"""Test root package exports."""

import monte_carlo


def test_package_exports() -> None:
    """Verify package __all__."""
    assert hasattr(monte_carlo, "SimulationParameters")
    assert hasattr(monte_carlo, "TrajectorySample")
    assert hasattr(monte_carlo, "SmoothedSurface")
    assert hasattr(monte_carlo, "SimulationEnginePort")
    assert hasattr(monte_carlo, "LocalMonteCarloEngine")
    assert hasattr(monte_carlo, "load_monte_carlo_pipeline")
