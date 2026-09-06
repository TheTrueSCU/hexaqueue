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
│   └── monte_carlo_simulation.yaml # Parameter sweep DAG pipeline with groups & collateral
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
│   ├── infra/                      # 4. Pipeline Loader & Collateral Resolvers
│   │   ├── __init__.py
│   │   ├── runner.py
│   │   └── scripts.py
│   ├── __init__.py
│   └── cli.py                      # 5. Common Executable Collateral Runner Script
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

## 4. Executable Collateral CLI (`src/monte_carlo/cli.py`)

Create `src/monte_carlo/cli.py` as an executable collateral script invoked by batch jobs for both simulation regimes and aggregation:

```python
"""Command-line entrypoint for Monte-Carlo simulation and smoothing collateral script."""

import argparse
import json
import math
from pathlib import Path
import random
import sys


def run_simulate(
    regime: str,
    seed: int,
    drift: float,
    vol: float,
    num_paths: int,
    steps: int,
    dt: float,
    initial_value: float,
    output_dir: Path,
) -> None:
    """Simulate geometric Brownian motion paths and save to output JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)  # noqa: S311

    drift_term = (drift - 0.5 * vol**2) * dt
    vol_term = vol * math.sqrt(dt)

    paths: list[list[float]] = []
    for _ in range(num_paths):
        path = [initial_value]
        current = initial_value
        for _ in range(steps - 1):
            u1 = rng.random()
            u2 = rng.random()
            z = math.sqrt(-2.0 * math.log(max(u1, 1e-12))) * math.cos(
                2.0 * math.pi * u2
            )
            current = current * math.exp(drift_term + vol_term * z)
            path.append(current)
        paths.append(path)

    out_file = output_dir / f"{regime}.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "regime": regime,
                "seed": seed,
                "drift": drift,
                "vol": vol,
                "paths": paths,
            },
            f,
        )

    print(
        f"[Monte-Carlo Worker] Simulated {regime}: "
        f"{len(paths)} paths, {steps} steps -> {out_file}"
    )


def run_aggregate(
    input_dir: Path,
    regimes: list[str],
    window_size: int,
) -> None:
    """Aggregate multiple simulated regimes, compute pointwise mean, and apply smoothing."""
    all_paths: list[list[float]] = []
    for reg in regimes:
        reg_file = input_dir / f"{reg}.json"
        if not reg_file.is_file():
            msg = f"Missing expected regime simulation output file: {reg_file}"
            raise FileNotFoundError(msg)

        with reg_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
            all_paths.extend(data["paths"])

    if not all_paths:
        msg = "No paths found for aggregation"
        raise ValueError(msg)

    total_paths = len(all_paths)
    steps = len(all_paths[0])

    mean_trajectory: list[float] = []
    for step_idx in range(steps):
        step_sum = sum(p[step_idx] for p in all_paths)
        mean_trajectory.append(step_sum / total_paths)

    smoothed: list[float] = []
    half_w = window_size // 2
    for i in range(steps):
        start = max(0, i - half_w)
        end = min(steps, i + half_w + 1)
        win = mean_trajectory[start:end]
        smoothed.append(sum(win) / len(win))

    terminals = [p[-1] for p in all_paths]
    term_mean = sum(terminals) / total_paths
    term_var = sum((v - term_mean) ** 2 for v in terminals) / total_paths
    std_err = math.sqrt(term_var) / math.sqrt(total_paths) if total_paths > 1 else 0.0

    print(
        f"[Monte-Carlo Aggregation Complete] Total Paths: {total_paths}, "
        f"Terminal Mean: {term_mean:.2f} (95% CI: [{term_mean - 1.96 * std_err:.2f}, {term_mean + 1.96 * std_err:.2f}]), "
        f"Smoothed T={steps}: {smoothed[-1]:.2f}"
    )


def main(argv: list[str] | None = None) -> int:
    """Main CLI parser entrypoint for monte carlo collateral script."""
    parser = argparse.ArgumentParser(
        description="Monte-Carlo simulation and smoothing worker script."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    sim_p = subparsers.add_parser("simulate", help="Run a single simulation regime.")
    sim_p.add_argument("--regime", type=str, required=True, help="Regime identifier")
    sim_p.add_argument("--seed", type=int, default=101, help="Random seed")
    sim_p.add_argument("--drift", type=float, default=0.05, help="Drift mu")
    sim_p.add_argument("--vol", type=float, default=0.20, help="Volatility sigma")
    sim_p.add_argument("--paths", type=int, default=50, help="Number of paths")
    sim_p.add_argument("--steps", type=int, default=100, help="Steps per path")
    sim_p.add_argument("--dt", type=float, default=0.01, help="Delta time increment")
    sim_p.add_argument(
        "--initial-value", type=float, default=100.0, help="Starting price/value"
    )
    sim_p.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for JSON results",
    )

    agg_p = subparsers.add_parser(
        "aggregate", help="Aggregate and smooth simulated regime outputs."
    )
    agg_p.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Input directory containing regime JSONs",
    )
    agg_p.add_argument(
        "--regimes", nargs="+", required=True, help="List of regime names"
    )
    agg_p.add_argument(
        "--window", type=int, default=5, help="Smoothing window size"
    )

    args = parser.parse_args(argv)

    if args.subcommand == "simulate":
        run_simulate(
            regime=args.regime,
            seed=args.seed,
            drift=args.drift,
            vol=args.vol,
            num_paths=args.paths,
            steps=args.steps,
            dt=args.dt,
            initial_value=args.initial_value,
            output_dir=args.output_dir,
        )
    elif args.subcommand == "aggregate":
        run_aggregate(
            input_dir=args.input_dir,
            regimes=args.regimes,
            window_size=args.window,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## 5. Multi-Regime Job Group DAG Specification

Define three parallel parameter regimes in a nested `groups` block referencing the collateral script in `pipelines/monte_carlo_simulation.yaml`:

```yaml
run:
  id: "monte-carlo-stochastic-sim"
  name: "Multi-Regime Monte-Carlo Simulation & Surface Smoothing"
  tags:
    - "simulation"
    - "monte-carlo"
    - "smoothing"
    - "collateral"
  env:
    SIM_DIR: "/tmp/mc_sim"
    SIM_SCRIPT: "../src/monte_carlo/cli.py"
  resources:
    cpus: 1
    ram_mb: 512
    scratch_mb: 100
    walltime_seconds: 15

groups:
  - id: "sim-regimes"
    name: "Stochastic Trajectory Simulation Regimes"
    params:
      - { regime: "low_vol", seed: 101, drift: 0.03, vol: 0.08, label: "Low Volatility" }
      - { regime: "mid_vol", seed: 202, drift: 0.05, vol: 0.18, label: "Medium Volatility" }
      - { regime: "high_vol", seed: 303, drift: 0.08, vol: 0.35, label: "High Volatility & Stress" }
    jobs:
      - id: "sim-regime-{{ regime }}"
        name: "Simulate {{ label }} Trajectories"
        command: "python {{ SIM_SCRIPT }} simulate --regime {{ regime }} --seed {{ seed }} --drift {{ drift }} --vol {{ vol }} --paths 50 --steps 100 --output-dir {{ SIM_DIR }}"

jobs:
  - id: "smooth-and-aggregate"
    name: "Multi-Variable Smoothing & Statistical Aggregation"
    command: "python {{ SIM_SCRIPT }} aggregate --input-dir {{ SIM_DIR }} --regimes low_vol mid_vol high_vol --window 5"
    depends_on:
      - "sim-regimes"
```

---

## 6. Running the Simulation via CLI

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

---

## 7. Direct Programmatic Pipeline Composition in Python

Hexaqueue pipelines are not limited to declarative YAML files. You can compose and execute pipelines directly within your Python applications using domain models (`RunSpec`, `JobGroupSpec`, `JobTemplateSpec`, and `GroupExpansionEngine`):

### Programmatic Builder (`src/monte_carlo/infra/builder.py`)

```python
"""Programmatic pipeline builder using Hexaqueue domain models and expansion engine."""

from pathlib import Path

from hexaqueue_core.domain.group import (
    GroupExpansionEngine,
    JobGroupSpec,
    JobTemplateSpec,
    ResourceOverrideSpec,
)
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_server.domain.models import RunSubmission


def build_monte_carlo_programmatic_pipeline(
    run_id: str = "monte-carlo-python-pipeline",
    sim_dir: str = "/tmp/mc_sim_python",
    num_paths: int = 50,
    steps: int = 100,
) -> RunSubmission:
    """Build a Monte-Carlo simulation pipeline programmatically via Python models."""
    script_path = Path(__file__).parent.parent / "cli.py"

    run_spec = RunSpec(
        id=run_id,
        name="Programmatic Monte-Carlo Simulation Pipeline",
        tags=["python", "simulation", "monte-carlo"],
    )

    simulation_group = JobGroupSpec(
        id="sim-regimes",
        name="Stochastic Simulation Regimes",
        params=[
            {
                "regime": "low_vol",
                "seed": 101,
                "drift": 0.03,
                "vol": 0.08,
                "label": "Low Volatility",
            },
            {
                "regime": "mid_vol",
                "seed": 202,
                "drift": 0.05,
                "vol": 0.18,
                "label": "Medium Volatility",
            },
            {
                "regime": "high_vol",
                "seed": 303,
                "drift": 0.08,
                "vol": 0.35,
                "label": "High Volatility & Stress",
            },
        ],
        env={
            "SIM_DIR": sim_dir,
            "SIM_SCRIPT": str(script_path.resolve()),
        },
        resources=ResourceOverrideSpec(
            cpus=1,
            ram_mb=512,
            scratch_mb=100,
            walltime_seconds=20,
        ),
        jobs=[
            JobTemplateSpec(
                id="sim-regime-{{ regime }}",
                name="Simulate {{ label }} Trajectories",
                command=(
                    f"python {{{{ SIM_SCRIPT }}}} simulate "
                    f"--regime {{{{ regime }}}} --seed {{{{ seed }}}} "
                    f"--drift {{{{ drift }}}} --vol {{{{ vol }}}} "
                    f"--paths {num_paths} --steps {steps} "
                    f"--output-dir {{{{ SIM_DIR }}}}"
                ),
            )
        ],
    )

    aggregation_job = JobTemplateSpec(
        id="smooth-and-aggregate",
        name="Surface Smoothing and Statistical Aggregation",
        command=f"python {script_path.resolve()} aggregate --input-dir {sim_dir} --regimes low_vol mid_vol high_vol --window 5",
        depends_on=["sim-regimes"],
        resources=ResourceOverrideSpec(
            cpus=1,
            ram_mb=512,
            walltime_seconds=20,
        ),
    )

    engine = GroupExpansionEngine(
        run_id=run_id,
        default_resources=ResourceRequirements(cpus=1, ram_mb=512),
    )

    resolved = engine.expand_groups(
        groups=[simulation_group],
        top_level_jobs=[aggregation_job],
    )

    return RunSubmission(
        run_spec=run_spec,
        jobs=resolved.jobs,
        dependencies=resolved.dependencies,
    )
```

### Running Directly from Python (`run_programmatic.py`)

```python
"""Execute Monte-Carlo pipeline programmatically."""

import asyncio
from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.domain.session import get_default_session
from hexaqueue_core.domain.lifecycle import RunState
from monte_carlo.infra.builder import build_monte_carlo_programmatic_pipeline


async def main() -> None:
    # 1. Build pipeline
    submission = build_monte_carlo_programmatic_pipeline()

    # 2. Connect to local session and submit
    session = get_default_session()
    await session.start()
    client = LocalClientAdapter(session=session)

    report = await client.submit_run(submission)
    print(f"Run '{report.run_id}' submitted ({report.total_jobs} jobs)")

    # 3. Await completion
    while report.state not in (RunState.DONE, RunState.BLOCKED):
        await asyncio.sleep(0.05)
        report = await client.get_run_status(report.run_id)

    print(f"✓ Run completed: {report.outcome}")
    await session.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

Execute with:
```bash
uv run python examples/monte-carlo/run_programmatic.py
```
