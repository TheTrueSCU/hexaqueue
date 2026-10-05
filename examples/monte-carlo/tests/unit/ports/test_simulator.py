"""Tests for simulator port."""

from monte_carlo.domain.models import (
    SimulationParameters,
    SmoothedSurface,
    TrajectorySample,
)
from monte_carlo.ports.simulator import SimulationEnginePort


class DummyEngine(SimulationEnginePort):
    def generate_paths(self, params: SimulationParameters) -> list[TrajectorySample]:
        return [TrajectorySample(path_id=0, values=[1.0, 2.0])]

    def smooth_trajectories(
        self, paths: list[TrajectorySample], window_size: int = 5
    ) -> SmoothedSurface:
        return SmoothedSurface(
            total_paths=1,
            mean_trajectory=[1.0, 2.0],
            moving_average_smoothed=[1.0, 2.0],
            terminal_mean=2.0,
            terminal_variance=0.0,
            confidence_interval_95=(2.0, 2.0),
        )


def test_dummy_engine() -> None:
    engine = DummyEngine()
    assert isinstance(engine, SimulationEnginePort)
