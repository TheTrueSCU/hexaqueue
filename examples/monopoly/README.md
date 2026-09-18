# monopoly

> Hexaqueue 100-Slot Cluster Monopoly Resolution & Fair-Share Preemption Example

Built with **[Hexaqueue](https://github.com/TheTrueSCU/hexaqueue)** — The Cloud-Agnostic HPC Batch Scheduler and Distributed Job Orchestrator.

---

## The Problem: The 100-Slot Cluster Monopoly

In multi-tenant high-performance computing (HPC) clusters, scheduling algorithms face a classic dilemma:

1. **The Monopoly Scenario**: A 100-slot cluster is fully occupied by Tenant A ("Team Alpha"), who submits 100 long-running background tasks.
2. **The Starvation Dilemma**: Tenant B ("Team Beta"), who holds equal 50% target entitlement, submits an urgent interactive analysis task.
3. **Naive FIFO Failure**: Under traditional FIFO queuing, Team Beta is completely starved and must wait hours or days for Team Alpha's jobs to finish.
4. **Naive Preemption Failure**: Under unconstrained preemption, jobs are preempted prematurely on transient queue spikes, resulting in massive wasted compute and scheduler thrashing.

---

## Hexaqueue's Architectural Solution

Hexaqueue resolves the 100-slot monopoly using four cooperating scheduling engines:

1. **Fair-Share Deficit Accounting (`FairShareTree`)**: Tracks normalized entitlement $E$ against decay-weighted historical usage $U_{\text{norm}}$. Team Beta incurs a large positive starvation deficit ($D = E - U_{\text{norm}} > 0$), while Team Alpha incurs an over-allocation deficit ($D < 0$).
2. **Anti-Thrashing Grace Period (`PreemptionPolicy.grace_period_seconds = 30.0`)**: Preemption is strictly inhibited while pending tasks have waited less than the grace period, absorbing transient queue fluctuations without killing running jobs.
3. **Starvation Deficit Threshold (`starvation_deficit_threshold = 0.4`)**: Controlled preemption triggers only when both the grace period has expired *and* the starving tenant's deficit exceeds the threshold.
4. **Smart Victim Selection & Compensation Bonus**: The scheduler selects the youngest checkpointable task from the over-allocated tenant to minimize lost computation, and awards the victim an immediate $+5000$ priority compensation bonus so it can quickly resume when resources free up.

---

## Architecture

```text
examples/monopoly/
├── pipelines/
│   └── monopoly_cluster.yaml     # Multi-Tenant DAG Pipeline Specification
├── src/monopoly/
│   ├── domain/                   # 1. Pure Domain Entities & Invariants
│   │   ├── __init__.py
│   │   └── models.py             # Workloads, Audit Records, Phase Results
│   ├── ports/                    # 2. Port Interfaces
│   │   ├── __init__.py
│   │   └── simulator.py          # ClusterSimulatorPort Contract
│   ├── adapters/                 # 3. Batch Scheduling Adapters
│   │   ├── __init__.py
│   │   └── scheduler.py          # BatchSchedulerClusterSimulator
│   └── infra/                    # 4. Presenter & Runner Wiring
│       ├── __init__.py
│       └── runner.py             # Rich Terminal Presenter & Lifecycle Runner
├── run_monopoly.py               # Standalone Interactive Executable Script
├── pyproject.toml
└── tests/
    └── unit/                     # 1:1 Parity Unit Tests
```

---

## Getting Started

### 1. Run Interactive Monopoly Simulation

Execute the full 3-phase simulation lifecycle with terminal visualization:

```bash
uv run python examples/monopoly/run_monopoly.py
```

Output:
```text
                 100-Slot Cluster Monopoly Resolution Lifecycle
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━━━┳━━━━━━┳━━━━━━━━┳┓
┃                                  ┃ Elaps… ┃ Alpha  ┃  Beta  ┃      ┃        ┃┃
┃ Phase                            ┃    (s) ┃ Slots  ┃ Slots  ┃ Pen… ┃ Preem… ┃┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━━━╇━━━━━━╇━━━━━━━━╇┩
│ Phase 1: 100-Slot Monopoly       │   0.0s │  100   │   0    │  0   │   0    ││
│ Established                      │        │        │        │      │        ││
│ Phase 2: Starvation & Grace      │  10.0s │  100   │   0    │  1   │   0    ││
│ Period Active                    │        │        │        │      │        ││
│ Phase 3: Controlled Preemption   │  35.0s │   99   │   1    │  0   │   1    ││
│ Authorized                       │        │        │        │      │        ││
└──────────────────────────────────┴────────┴────────┴────────┴──────┴────────┴┘

                       Controlled Preemption Audit Trail
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ Victim Job    ┃ Victim Tenant ┃ Starved Tenant┃ Compensation  ┃ Reason       ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ alpha-job-000 │ team_alpha    │ team_beta     │         +5000 │ Preempted to │
│               │               │               │               │ resolve      │
│               │               │               │               │ fair-share   │
│               │               │               │               │ starvation   │
└───────────────┴───────────────┴───────────────┴───────────────┴──────────────┘
```

### 2. Submit Multi-Tenant Pipeline via `hq` CLI

```bash
# Submit multi-tenant workload with live progress streaming
uv run hq run submit examples/monopoly/pipelines/monopoly_cluster.yaml --watch
```

### 3. Queue Explainability & Scheduling Diagnostics

```bash
# Explain why an urgent job is waiting
uv run hq why beta-urgent-task

# Rich priority calculation, deficit breakdown, and blockers
uv run hq explain beta-urgent-task

# Inspect hierarchical fair-share tree and usage decay
uv run hq fairshare
```

### 4. Run Test Suite

```bash
uv run hexaqual test run -e monopoly
```
