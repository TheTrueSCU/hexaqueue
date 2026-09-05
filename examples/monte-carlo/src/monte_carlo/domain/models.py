"""Domain models for Monte-Carlo simulation and trajectory smoothing."""

import math
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SimulationParameters(BaseModel):
    """Parameters defining a stochastic simulation run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    drift: float = Field(default=0.05, description="Expected drift rate")
    dt: float = Field(default=0.01, gt=0.0, description="Time delta step size")
    initial_value: float = Field(gt=0.0, description="Starting asset or state value")
    num_paths: int = Field(ge=1, description="Number of sample paths to simulate")
    seed: int = Field(default=42, description="Random seed for reproducibility")
    steps: int = Field(ge=2, description="Number of simulation steps")
    volatility: float = Field(
        default=0.2, ge=0.0, description="Volatility scale parameter"
    )


class TrajectorySample(BaseModel):
    """Single generated stochastic path trajectory."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path_id: int = Field(ge=0, description="Path index")
    values: list[float] = Field(min_length=2, description="Generated trajectory values")


class SmoothedSurface(BaseModel):
    """Smoothed trajectory metrics across multi-variable simulation paths."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    confidence_interval_95: tuple[float, float] = Field(
        description="95% confidence bounds (lower, upper)"
    )
    mean_trajectory: list[float] = Field(description="Pointwise mean across all paths")
    moving_average_smoothed: list[float] = Field(
        description="Smoothed moving average trajectory"
    )
    terminal_mean: float = Field(description="Mean terminal value")
    terminal_variance: float = Field(ge=0.0, description="Terminal value variance")
    total_paths: int = Field(ge=1, description="Total analyzed paths count")

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate confidence bounds ordering."""
        lower, upper = self.confidence_interval_95
        if lower > upper:
            msg = f"Lower bound ({lower}) exceeds upper bound ({upper})"
            raise ValueError(msg)
        if math.isnan(self.terminal_mean) or math.isinf(self.terminal_mean):
            msg = "Terminal mean must be a finite number"
            raise ValueError(msg)
        return self


__all__ = [
    "SimulationParameters",
    "SmoothedSurface",
    "TrajectorySample",
]
