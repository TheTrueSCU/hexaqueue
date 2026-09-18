# Tutorial 3: Resolving the 100-Slot Monopoly with Fair-Share & Controlled Preemption

Welcome to Tutorial 3 for **Hexaqueue**!

In this tutorial, you will explore how Hexaqueue solves one of the most notoriously difficult challenges in multi-tenant high-performance computing (HPC) and distributed batch scheduling: **The 100-Slot Cluster Monopoly**.

By the end of this tutorial, you will understand:
- Why naive First-In, First-Out (FIFO) queuing causes catastrophic starvation for high-priority or newly arrived tenants.
- Why naive unconstrained preemption leads to scheduler thrashing and massive wasted compute.
- How Hexaqueue's **Fair-Share Deficit Trees**, **Anti-Thrashing Grace Periods**, and **Controlled Preemption Engine** achieve mathematical equilibrium without thrashing.
- How to inspect scheduler decisions transparently using `hq why`, `hq explain`, and `hq fairshare`.
- How to write clean, hexagonal domain models, ports, and adapters with 100% test parity.

---

## 1. The Thought Experiment: The 100-Slot Monopoly

Imagine a shared compute cluster with a fixed capacity of **100 execution slots**:

```
                              Total Cluster Capacity: 100 Slots
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ [Slot 001] [Slot 002] [Slot 003] ... [Slot 049] [Slot 050] ... [Slot 098] [Slot 099] [Slot 100]  │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Two research teams share this cluster under equal 50/50 entitlement ($\text{Shares}_{\text{Alpha}} = 1.0, \text{Shares}_{\text{Beta}} = 1.0$):

1. **Phase 1: The Monopoly (t = 0s)**:
   Team Alpha arrives first and submits 100 long-running simulation jobs (each needing 1 slot, runtime = 1 hour). The scheduler allocates all 100 slots to Team Alpha. The cluster is at 100% utilization.
2. **Phase 2: The Urgent Arrival & Starvation (t = 10s)**:
   Team Beta submits an urgent analytics query. Every slot is occupied. Under traditional FIFO scheduling, Team Beta must wait an entire hour.
3. **The Preemption Dilemma**:
   If the scheduler kills Team Alpha's jobs immediately whenever anyone else arrives, transient queue spikes will cause endless job aborts and restarts—a phenomenon known as **scheduler thrashing**.
4. **Hexaqueue's Solution**:
   - **Anti-Thrashing Grace Period**: Team Beta is given a grace period (e.g. 30 seconds) during which preemption is withheld to see if slots naturally free up.
   - **Fair-Share Starvation Deficit**: As Team Beta waits, its starvation deficit accumulates:
     $$D = \text{Entitlement} - \text{Normalized Usage}$$
   - **Controlled Preemption (t = 35s)**: Once wait time exceeds the grace period ($35\text{s} > 30\text{s}$) and starvation deficit exceeds the configured threshold ($D > 0.4$), the scheduler triggers a surgical preemption.
   - **Smart Victim Selection**: The scheduler selects the youngest checkpointable job from Team Alpha (minimizing wasted compute).
   - **Compensation Priority Bonus**: The preempted task is granted a priority bonus ($+5000$) so it immediately jumps to the front of the queue when slots become available.

---

## 2. Project Architecture

Our monopoly demonstration is organized as an independent hexagonal package in `examples/monopoly`:

```text
examples/monopoly/
├── pipelines/
│   └── monopoly_cluster.yaml     # Declarative Multi-Tenant Workflow Spec
├── src/monopoly/
│   ├── domain/                   # 1. Pure Domain Entities & Invariants
│   │   ├── __init__.py
│   │   └── models.py             # TenantWorkload, PreemptionAuditRecord, PhaseResult
│   ├── ports/                    # 2. Abstract Port Contract
│   │   ├── __init__.py
│   │   └── simulator.py          # ClusterSimulatorPort
│   ├── adapters/                 # 3. Hexaqueue Scheduling Adapter
│   │   ├── __init__.py
│   │   └── scheduler.py          # BatchSchedulerClusterSimulator
│   └── infra/                    # 4. Rich Terminal Presenter & Runner
│       ├── __init__.py
│       └── runner.py             # Simulation Lifecycle & Dashboard
├── run_monopoly.py               # Standalone Executable CLI Script
├── pyproject.toml
└── tests/
    └── unit/                     # 1:1 Parity Unit Tests (100% Coverage)
```

---

## 3. Defining Domain Models (`src/monopoly/domain/models.py`)

Create `src/monopoly/domain/models.py` with strict Pydantic validation:

```python
"""Domain entities and value objects for the 100-slot monopoly scenario."""

from pydantic import BaseModel, ConfigDict, Field


class TenantWorkload(BaseModel):
    """Specification of a tenant's batch or interactive workload."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str = Field(min_length=1, description="Tenant identifier")
    shares: float = Field(default=1.0, gt=0.0, description="Fair-share entitlement shares")
    job_count: int = Field(gt=0, description="Total jobs submitted")
    checkpointable: bool = Field(default=False, description="Whether jobs support checkpointing")
    walltime_seconds: float = Field(default=100.0, gt=0.0, description="Job walltime in seconds")


class PreemptionAuditRecord(BaseModel):
    """Audit record capturing a controlled preemption event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    preempted_job_id: str = Field(description="Victim job ID")
    victim_tenant: str = Field(description="Victim tenant ID")
    starved_tenant: str = Field(description="Starved tenant ID")
    reason: str = Field(description="Explanation of preemption")
    timestamp: float = Field(ge=0.0, description="Preemption timestamp")
    compensation_bonus: float = Field(ge=0.0, description="Granted compensation bonus")


class SimulationPhaseResult(BaseModel):
    """Snapshot of cluster slot allocation and queue state during a simulation phase."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_name: str = Field(description="Simulation phase name")
    elapsed_seconds: float = Field(ge=0.0, description="Elapsed simulation seconds")
    used_slots: int = Field(ge=0, description="Currently allocated slots")
    available_slots: int = Field(ge=0, description="Currently idle slots")
    slots_tenant_a: int = Field(ge=0, description="Slots held by Tenant A")
    slots_tenant_b: int = Field(ge=0, description="Slots held by Tenant B")
    pending_jobs_count: int = Field(ge=0, description="Number of waiting jobs")
    preempted_jobs_count: int = Field(ge=0, description="Preemptions in this phase")
    notes: str = Field(description="Scheduling notes")


__all__ = [
    "PreemptionAuditRecord",
    "SimulationPhaseResult",
    "TenantWorkload",
]
```

---

## 4. Port Contract (`src/monopoly/ports/simulator.py`)

The simulator port decouples the scenario orchestration from the underlying batch scheduling engine:

```python
"""Abstract port interface for cluster monopoly simulation."""

from abc import ABC, abstractmethod
from monopoly.domain.models import (
    PreemptionAuditRecord,
    SimulationPhaseResult,
    TenantWorkload,
)


class ClusterSimulatorPort(ABC):
    """Abstract cluster simulation port interface."""

    @abstractmethod
    def initialize_cluster(self, total_slots: int = 100) -> None:
        """Initialize the cluster resource pool with specified slot capacity."""

    @abstractmethod
    def setup_tenants(
        self, tenant_a: TenantWorkload, tenant_b: TenantWorkload
    ) -> None:
        """Configure fair-share tree and tenants for the simulation."""

    @abstractmethod
    def run_monopoly_phase(self) -> SimulationPhaseResult:
        """Execute Phase 1: Tenant A occupies all 100 cluster slots."""

    @abstractmethod
    def run_starvation_phase(self, elapsed_seconds: float = 10.0) -> SimulationPhaseResult:
        """Execute Phase 2: Tenant B submits urgent jobs during grace period."""

    @abstractmethod
    def run_preemption_phase(self, elapsed_seconds: float = 35.0) -> SimulationPhaseResult:
        """Execute Phase 3: Grace period expires and controlled preemption triggers."""

    @abstractmethod
    def get_audit_log(self) -> list[PreemptionAuditRecord]:
        """Retrieve historical preemption audit records."""


__all__ = [
    "ClusterSimulatorPort",
]
```

---

## 5. Hexaqueue Scheduling Adapter (`src/monopoly/adapters/scheduler.py`)

Our adapter wires together Hexaqueue's core scheduling engines: `ResourceSlotPool`, `FairShareTree`, `ControlledPreemptionEngine`, and `BatchSchedulerEngine`:

```python
"""Batch scheduler cluster simulation adapter."""

from datetime import UTC, datetime, timedelta

from hexaqueue_core.domain.fairshare import FairShareNode, FairShareTree
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.scheduling import (
    BatchSchedulerEngine,
    ControlledPreemptionEngine,
    PreemptionPolicy,
    ResourceSlotPool,
)
from monopoly.domain.models import (
    PreemptionAuditRecord,
    SimulationPhaseResult,
    TenantWorkload,
)
from monopoly.ports.simulator import ClusterSimulatorPort


class BatchSchedulerClusterSimulator(ClusterSimulatorPort):
    """Concrete cluster simulator powered by Hexaqueue scheduling engines."""

    def __init__(
        self,
        total_slots: int = 100,
        grace_period_seconds: float = 30.0,
        starvation_deficit_threshold: float = 0.4,
        preemption_bonus: float = 5000.0,
    ) -> None:
        self.total_slots = total_slots
        self.grace_period_seconds = grace_period_seconds
        self.starvation_deficit_threshold = starvation_deficit_threshold
        self.preemption_bonus = preemption_bonus

        self.pool = ResourceSlotPool(total_slots=total_slots)
        self.fs_tree = FairShareTree(root_id="cluster")
        self.preemption_policy = PreemptionPolicy(
            grace_period_seconds=grace_period_seconds,
            starvation_deficit_threshold=starvation_deficit_threshold,
            preemption_bonus=preemption_bonus,
        )
        self.scheduler = BatchSchedulerEngine(
            pool=self.pool,
            fairshare_tree=self.fs_tree,
            preemption_engine=ControlledPreemptionEngine(policy=self.preemption_policy),
        )
        self._t0 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
        self._t0_secs = self._t0.timestamp()
        self._running_jobs_a: list[JobSpec] = []
        self._pending_jobs_b: list[JobSpec] = []
        self._audit_log: list[PreemptionAuditRecord] = []
        self._tenant_a: TenantWorkload | None = None
        self._tenant_b: TenantWorkload | None = None
        # ... methods: initialize_cluster, setup_tenants, run_monopoly_phase, run_starvation_phase, run_preemption_phase
```

---

## 6. Running the Interactive Demonstration

Execute the demonstration directly with UV:

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

╭────────────────── Hexaqueue Scheduling Guardrails Verified ──────────────────╮
│ ✓ 100-Slot Monopoly Successfully Resolved                                    │
│ • Anti-thrashing grace period prevented early kills at t=10s                 │
│ • Fair-share deficit threshold (>0.4) safely triggered preemption at t=35s   │
│ • Youngest checkpointable task was selected as victim to minimize compute    │
│ loss                                                                         │
│ • Preempted task received +5000 priority compensation bonus for rapid        │
│ recovery                                                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

---

## 7. Declarative Multi-Tenant Pipeline (`pipelines/monopoly_cluster.yaml`)

We can also express this workload declaratively in YAML with deliberate artificial delays:

```yaml
run:
  id: "cluster-monopoly-demo"
  name: "100-Slot Multi-Tenant Cluster Monopoly & Preemption Demo"
  tags:
    - "tutorial"
    - "monopoly"
    - "fair-share"
    - "preemption"

groups:
  - id: "alpha-workload"
    name: "Team Alpha Background Batch Jobs"
    params:
      - { batch_id: "01", user: "team_alpha" }
      - { batch_id: "02", user: "team_alpha" }
      - { batch_id: "03", user: "team_alpha" }
    jobs:
      - id: "alpha-batch-{{ batch_id }}"
        name: "Alpha Batch Job {{ batch_id }}"
        command: "python -c \"import time; time.sleep(2.0); print('Team Alpha batch completed')\""
        resources:
          cpus: 1
          ram_mb: 512
          scratch_mb: 50
          walltime_seconds: 30

jobs:
  - id: "beta-urgent-task"
    name: "Team Beta Urgent Analytics Task"
    command: "python -c \"import time; time.sleep(1.5); print('Team Beta high-priority workload completed')\""
    resources:
      cpus: 1
      ram_mb: 512
      scratch_mb: 50
      walltime_seconds: 30
```

Submit and stream via `hq`:

```bash
uv run hq run submit examples/monopoly/pipelines/monopoly_cluster.yaml --watch
```

---

## 8. Transparent Scheduler Explainability

While tasks are executing, you can interrogate the scheduler directly from the terminal:

### 1. 1-Line Queue Reason (`hq why`)

```bash
uv run hq why beta-urgent-task
```

Output:
```text
Job 'beta-urgent-task' is waiting: fair-share starvation deficit (0.50) under 30s grace period.
```

### 2. Rich Priority Math & Blockers (`hq explain`)

```bash
uv run hq explain beta-urgent-task
```

Output displays:
- Base priority vs age-accrued priority bonus.
- Starvation deficit calculation ($D = 0.50$).
- Active blockers (slot capacity saturation).
- Preemption recommendation with candidate victim list.

### 3. Fair-Share Tree Hierarchy (`hq fairshare`)

```bash
uv run hq fairshare
```

Displays the current entitlement weights, usage decay half-life, and normalized usage per tenant.

---

## 9. Running Unit & Parity Tests

Execute the 100% test suite for the monopoly package:

```bash
uv run hexaqual test run -e monopoly
```

---

## 10. Summary & What's Next

### What You've Learned 🎓
- How multi-tenant cluster monopolies lead to tenant starvation and how naive preemption leads to thrashing.
- How Hexaqueue uses `FairShareTree`, `PreemptionPolicy`, and `ControlledPreemptionEngine` to resolve monopolies safely.
- How anti-thrashing grace periods protect running jobs from transient queue spikes.
- How victim selection prioritizes checkpointable, youngest jobs to conserve compute time.
- How priority compensation bonuses prevent victim jobs from remaining starved.

### Up Next 🚀
- **Tutorial 4: Containerized Execution with Rootless Podman & Apptainer**
- **Tutorial 5: Direct-to-Storage Presigned Collateral Ingestion & Security Quarantine Scanning**
- **Tutorial 6: Cloud Batch Deference & Hybrid Scheduling on Slurm / Kubernetes Kueue**
