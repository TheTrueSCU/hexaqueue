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

### 1. Execute Parallel Monte-Carlo DAG with Live Watch

Each simulation and aggregation worker includes a configurable artificial delay (`--delay 1.5`) so developers can observe parallel multi-regime execution and query queue metrics in real time:

```bash
# Submit and stream live DAG execution
uv run hq run submit examples/monte-carlo/pipelines/monte_carlo_simulation.yaml --watch
```

### 2. Free-Tier Safety Mode ($0 Cloud Spend Guard)

Clamp worker allocations and verify zero-cost boundary compliance:

```bash
uv run hq run submit examples/monte-carlo/pipelines/monte_carlo_simulation.yaml --watch --free-tier
```

### 3. Queue Explainability & Scheduling Diagnostics

Inspect scheduling decisions, dependencies, and fair-share trees:

```bash
# Query why aggregation job is waiting for regime simulations
uv run hq why smooth-and-aggregate

# Inspect priority math and dependency blockers
uv run hq explain smooth-and-aggregate

# View cluster fair-share hierarchy
uv run hq fairshare
```

### 4. View Captured Output Logs

```bash
uv run hq logs smooth-and-aggregate
```

### 5. Programmatic Pipeline Execution

You can also submit and monitor workflows programmatically from Python:

```bash
uv run python examples/monte-carlo/run_programmatic.py
```

### 6. Run Test Suite

```bash
uv run hexaqual test run -e monte-carlo
```
