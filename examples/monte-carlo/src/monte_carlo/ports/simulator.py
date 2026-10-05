"""Port interfaces for stochastic simulation and smoothing."""

from abc import ABC, abstractmethod

from monte_carlo.domain.models import (
    SimulationParameters,
    SmoothedSurface,
    TrajectorySample,
)


class SimulationEnginePort(ABC):
    """Abstract port interface for executing Monte-Carlo simulations."""

    @abstractmethod
    def generate_paths(self, params: SimulationParameters) -> list[TrajectorySample]:
        """Generate stochastic sample trajectories."""

    @abstractmethod
    def smooth_trajectories(
        self, paths: list[TrajectorySample], window_size: int = 5
    ) -> SmoothedSurface:
        """Compute aggregate statistics and moving average smoothing."""


__all__ = [
    "SimulationEnginePort",
]
