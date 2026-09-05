# monte-carlo

> Hexaqueue Parallel Monte-Carlo Simulation & Multi-Variable Surface Smoothing Example

Built with **[Hexaqueue](https://github.com/TheTrueSCU/hexaqueue)** — The Cloud-Agnostic HPC Batch Scheduler and Distributed Job Orchestrator.

## Architecture

This project demonstrates parallel parameter sweeping across volatility/drift regimes and downstream statistical smoothing over stochastic trajectories:

```text
examples/monte-carlo/
├── pipelines/
│   └── monte_carlo_simulation.yaml # Parallel Multi-Regime DAG Specification
├── src/monte_carlo/
│   ├── domain/                     # Stochastic models & smoothed surfaces
│   │   ├── __init__.py
│   │   └── models.py
│   ├── ports/                      # Simulation & smoothing port interfaces
│   │   ├── __init__.py
│   │   └── simulator.py
│   ├── adapters/                   # Geometric Brownian Motion & Moving Average smoother
│   │   ├── __init__.py
│   │   └── local.py
│   └── infra/                      # Pipeline loader
│       ├── __init__.py
│       └── runner.py
└── tests/
    └── unit/                       # 1:1 Parity Unit Tests
```

## Getting Started

```bash
# 1. Execute parallel Monte-Carlo DAG
uv run hq run submit examples/monte-carlo/pipelines/monte_carlo_simulation.yaml --watch

# 2. View aggregation output
uv run hq logs smooth-and-aggregate

# 3. Run test suite
PYTHONPATH=examples/monte-carlo/src uv run pytest examples/monte-carlo/tests
```
