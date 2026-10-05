"""Tests for LocalMonteCarloEngine adapter."""

import pytest

from monte_carlo.adapters.local import LocalMonteCarloEngine
from monte_carlo.domain.models import SimulationParameters


def test_local_monte_carlo_simulation_and_smoothing() -> None:
    """Verify stochastic path generation and statistical smoothing."""
    engine = LocalMonteCarloEngine()
    params = SimulationParameters(
        initial_value=100.0,
        drift=0.05,
        volatility=0.2,
        dt=0.01,
        steps=50,
        num_paths=20,
        seed=123,
    )

    paths = engine.generate_paths(params)
    assert len(paths) == 20
    assert len(paths[0].values) == 50
    assert paths[0].values[0] == 100.0

    surface = engine.smooth_trajectories(paths, window_size=5)
    assert surface.total_paths == 20
    assert len(surface.mean_trajectory) == 50
    assert len(surface.moving_average_smoothed) == 50
    assert surface.confidence_interval_95[0] <= surface.confidence_interval_95[1]

    with pytest.raises(ValueError, match="Cannot smooth empty"):
        engine.smooth_trajectories([])
