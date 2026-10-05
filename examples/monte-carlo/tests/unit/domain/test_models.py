"""Tests for domain models."""

import pytest

from monte_carlo.domain.models import (
    SimulationParameters,
    SmoothedSurface,
    TrajectorySample,
)


def test_simulation_parameters_defaults() -> None:
    """Verify default parameters."""
    params = SimulationParameters(initial_value=100.0, num_paths=10, steps=5)
    assert params.initial_value == 100.0
    assert params.drift == 0.05
    assert params.dt == 0.01
    assert params.volatility == 0.2


def test_trajectory_sample() -> None:
    """Verify TrajectorySample."""
    sample = TrajectorySample(path_id=0, values=[100.0, 101.5, 102.0])
    assert sample.path_id == 0
    assert len(sample.values) == 3


def test_smoothed_surface_validation() -> None:
    """Verify SmoothedSurface validation."""
    surface = SmoothedSurface(
        total_paths=10,
        mean_trajectory=[100.0, 101.0],
        moving_average_smoothed=[100.0, 101.0],
        terminal_mean=101.0,
        terminal_variance=2.5,
        confidence_interval_95=(98.0, 104.0),
    )
    assert surface.total_paths == 10

    with pytest.raises(ValueError, match="exceeds upper bound"):
        SmoothedSurface(
            total_paths=10,
            mean_trajectory=[100.0, 101.0],
            moving_average_smoothed=[100.0, 101.0],
            terminal_mean=101.0,
            terminal_variance=2.5,
            confidence_interval_95=(105.0, 95.0),
        )
