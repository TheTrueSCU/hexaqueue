"""Local Monte-Carlo simulator and smoothing engine adapter."""

import math
import random

from monte_carlo.domain.models import (
    SimulationParameters,
    SmoothedSurface,
    TrajectorySample,
)
from monte_carlo.ports.simulator import SimulationEnginePort


class LocalMonteCarloEngine(SimulationEnginePort):
    """In-memory Geometric Brownian Motion simulator and Gaussian/SMA smoother."""

    def generate_paths(self, params: SimulationParameters) -> list[TrajectorySample]:
        """Generate stochastic trajectories via geometric Brownian motion."""
        rng = random.Random(params.seed)  # noqa: S311
        results: list[TrajectorySample] = []

        drift_term = (params.drift - 0.5 * params.volatility**2) * params.dt
        vol_term = params.volatility * math.sqrt(params.dt)

        for path_id in range(params.num_paths):
            path_values = [params.initial_value]
            current = params.initial_value

            for _ in range(params.steps - 1):
                # Box-Muller standard normal
                u1 = rng.random()
                u2 = rng.random()
                z = math.sqrt(-2.0 * math.log(max(u1, 1e-12))) * math.cos(
                    2.0 * math.pi * u2
                )

                current = current * math.exp(drift_term + vol_term * z)
                path_values.append(current)

            results.append(TrajectorySample(path_id=path_id, values=path_values))

        return results

    def smooth_trajectories(
        self, paths: list[TrajectorySample], window_size: int = 5
    ) -> SmoothedSurface:
        """Compute aggregate statistics and simple moving average smoothing."""
        if not paths:
            msg = "Cannot smooth empty trajectory list"
            raise ValueError(msg)

        num_steps = len(paths[0].values)
        num_paths = len(paths)

        # 1. Pointwise mean
        mean_trajectory: list[float] = []
        for step_idx in range(num_steps):
            step_sum = sum(p.values[step_idx] for p in paths)
            mean_trajectory.append(step_sum / num_paths)

        # 2. Moving average smoothing
        smoothed: list[float] = []
        half_w = window_size // 2
        for i in range(num_steps):
            start = max(0, i - half_w)
            end = min(num_steps, i + half_w + 1)
            window = mean_trajectory[start:end]
            smoothed.append(sum(window) / len(window))

        # 3. Terminal statistics
        terminal_values = [p.values[-1] for p in paths]
        term_mean = sum(terminal_values) / num_paths
        term_var = sum((v - term_mean) ** 2 for v in terminal_values) / num_paths
        std_err = math.sqrt(term_var) / math.sqrt(num_paths) if num_paths > 1 else 0.0

        ci_lower = term_mean - 1.96 * std_err
        ci_upper = term_mean + 1.96 * std_err

        return SmoothedSurface(
            total_paths=num_paths,
            mean_trajectory=mean_trajectory,
            moving_average_smoothed=smoothed,
            terminal_mean=term_mean,
            terminal_variance=term_var,
            confidence_interval_95=(ci_lower, ci_upper),
        )


__all__ = [
    "LocalMonteCarloEngine",
]
