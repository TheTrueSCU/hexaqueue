# Tutorial 2: Parallel Monte-Carlo Simulation & Multi-Variable Smoothing

Welcome to Tutorial 2 for **Hexaqueue**!

In this guide, you will learn how to build a high-throughput **Monte-Carlo simulation workflow** with Hexaqueue. We will run parameter sweeps across multiple volatility/drift market regimes in parallel, and aggregate the resulting stochastic paths with moving average surface smoothing and 95% confidence bounds.

By the end of this tutorial, you will have:

- Built a pure domain model for stochastic simulation parameters (`SimulationParameters`, `TrajectorySample`, `SmoothedSurface`).
- Implemented Geometric Brownian Motion (GBM) simulation and statistical trajectory smoothing.
- Configured a multi-branch parallel DAG pipeline in YAML.
- Executed and inspected the simulation using the `hq` CLI developer toolchain.

---

## 1. Project Architecture

```text
examples/monte-carlo/
├── pipelines/
│   └── monte_carlo_simulation.yaml # Parallel Multi-Regime Simulation DAG
├── src/monte_carlo/
│   ├── domain/                     # 1. Pure Domain Entities & Invariants
│   │   ├── __init__.py
│   │   └── models.py
│   ├── ports/                      # 2. Simulation & Smoothing Port Interfaces
│   │   ├── __init__.py
│   │   └── simulator.py
│   ├── adapters/                   # 3. Geometric Brownian Motion & Moving Average Smoother
│   │   ├── __init__.py
│   │   └── local.py
│   └── infra/                      # 4. Pipeline Loader
│       ├── __init__.py
│       └── runner.py
└── tests/
    └── unit/                       # 1:1 Parity Unit Tests
```

---

## 2. Stochastic Domain Models

Create `src/monte_carlo/domain/models.py`:

```python
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
```

---

## 3. Simulator Ports & Local Engine Adapter

### Simulator Port (`src/monte_carlo/ports/simulator.py`)

```python
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
```

### Local Engine Adapter (`src/monte_carlo/adapters/local.py`)

```python
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
```

---

## 4. Multi-Regime Simulation DAG Specification

Define three parallel parameter regimes (low, mid, high volatility) feeding into a single smoothing and aggregation step in `pipelines/monte_carlo_simulation.yaml`:

```yaml
run:
  id: "monte-carlo-stochastic-sim"
  name: "Multi-Regime Monte-Carlo Simulation & Surface Smoothing"
  tags:
    - "simulation"
    - "monte-carlo"
    - "smoothing"

jobs:
  - id: "sim-regime-low-vol"
    name: "Simulate Low Volatility Trajectories"
    command: "python -c \"import json, os, random, math; os.makedirs('/tmp/mc_sim', exist_ok=True); rng = random.Random(101); paths = [[100.0] for _ in range(50)]; [p.append(p[-1] * math.exp((0.03 - 0.5*0.08**2)*0.01 + 0.08*math.sqrt(0.01)*rng.gauss(0,1))) for p in paths for _ in range(99)]; json.dump({'regime': 'low_vol', 'paths': paths}, open('/tmp/mc_sim/low_vol.json', 'w')); print('Low-vol regime simulated: 50 paths, 100 steps')\""
    resources:
      cpus: 1
      ram_mb: 512
      scratch_mb: 100
      walltime_seconds: 15

  - id: "sim-regime-mid-vol"
    name: "Simulate Medium Volatility Trajectories"
    command: "python -c \"import json, os, random, math; os.makedirs('/tmp/mc_sim', exist_ok=True); rng = random.Random(202); paths = [[100.0] for _ in range(50)]; [p.append(p[-1] * math.exp((0.05 - 0.5*0.18**2)*0.01 + 0.18*math.sqrt(0.01)*rng.gauss(0,1))) for p in paths for _ in range(99)]; json.dump({'regime': 'mid_vol', 'paths': paths}, open('/tmp/mc_sim/mid_vol.json', 'w')); print('Mid-vol regime simulated: 50 paths, 100 steps')\""
    resources:
      cpus: 1
      ram_mb: 512
      scratch_mb: 100
      walltime_seconds: 15

  - id: "sim-regime-high-vol"
    name: "Simulate High Volatility & Stress Trajectories"
    command: "python -c \"import json, os, random, math; os.makedirs('/tmp/mc_sim', exist_ok=True); rng = random.Random(303); paths = [[100.0] for _ in range(50)]; [p.append(p[-1] * math.exp((0.08 - 0.5*0.35**2)*0.01 + 0.35*math.sqrt(0.01)*rng.gauss(0,1))) for p in paths for _ in range(99)]; json.dump({'regime': 'high_vol', 'paths': paths}, open('/tmp/mc_sim/high_vol.json', 'w')); print('High-vol regime simulated: 50 paths, 100 steps')\""
    resources:
      cpus: 1
      ram_mb: 512
      scratch_mb: 100
      walltime_seconds: 15

  - id: "smooth-and-aggregate"
    name: "Multi-Variable Smoothing & Statistical Aggregation"
    command: "python -c \"import json; low = json.load(open('/tmp/mc_sim/low_vol.json'))['paths']; mid = json.load(open('/tmp/mc_sim/mid_vol.json'))['paths']; high = json.load(open('/tmp/mc_sim/high_vol.json'))['paths']; all_paths = low + mid + high; steps = len(all_paths[0]); mean_traj = [sum(p[s] for p in all_paths)/len(all_paths) for s in range(steps)]; smoothed = [sum(mean_traj[max(0, i-2):min(steps, i+3)])/len(mean_traj[max(0, i-2):min(steps, i+3)]) for i in range(steps)]; term = [p[-1] for p in all_paths]; print(f'Monte-Carlo Aggregation Complete! Total Paths: {len(all_paths)}, Terminal Mean: {sum(term)/len(term):.2f}, Smoothed T=100: {smoothed[-1]:.2f}')\""
    depends_on:
      - "sim-regime-low-vol"
      - "sim-regime-mid-vol"
      - "sim-regime-high-vol"
    resources:
      cpus: 1
      ram_mb: 512
      scratch_mb: 100
      walltime_seconds: 15
```

---

## 5. Running the Simulation

```bash
uv run hq run submit examples/monte-carlo/pipelines/monte_carlo_simulation.yaml --watch
```

Output:
```text
✓ Run 'monte-carlo-stochastic-sim' submitted (4 jobs)
Run completed with status: SUCCEEDED
Run Summary: monte-carlo-stochastic-sim 
┏━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┓
┃ Total ┃ Completed ┃ Failed ┃ Pending ┃
┡━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━┩
│   4   │     4     │   0    │    0    │
└───────┴───────────┴────────┴─────────┘
```
