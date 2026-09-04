# 🧩 `hexaqueue-core`

> Pure domain models, lifecycle state machines, scheduling algorithms, and hexagonal port interfaces for Hexaqueue.

---

## 🏗️ Architecture & Dependencies

```mermaid
graph TD
    subgraph S1["Hexaqueue Dependents"]
        CLI["hexaqueue-cli"]
        SERVER["hexaqueue-server"]
        WORKER["hexaqueue-worker"]
        COLLATERAL["hexaqueue-collateral"]
        SCANNER["hexaqueue-scanner"]
        MONITOR["hexaqueue-monitor"]
        DASH["hexaqueue-dashboard"]
    end

    subgraph S2["hexaqueue-core"]
        DOMAIN["domain (Job, Task, Collateral, Hierarchy, State Machines)"]
        PORTS["ports (ComputeResource, Storage, Scanner, LogStream, Budget)"]
    end

    subgraph S3["Hexastack Foundation"]
        HS_CORE["hexastack-core (DI rodi & base ports)"]
        HS_CQRS["hexastack-cqrs (Commands, Queries, Events)"]
    end

    CLI --> S2
    SERVER --> S2
    WORKER --> S2
    COLLATERAL --> S2
    SCANNER --> S2
    MONITOR --> S2
    DASH --> S2

    S2 --> HS_CORE
    S2 --> HS_CQRS
```

---

## 🔑 Key Responsibilities
- **Domain Entities**: `JobSpec`, `TaskSpec`, `RunSpec`, `CollateralBundle`, `ResourceRequirements`.
- **Lifecycle State Machines**: `JobState` (`SUBMITTED`, `BLOCKED`, `PENDING`, `PROVISIONING`, `RUNNING`, `CLEANUP`, `DONE`) and aggregated `RunState` roll-up.
- **Hexagonal Ports**: `ComputeResourcePort`, `StorageVolumePort`, `ExecutionRuntimePort`, `BudgetAccountingPort`, `CostRateModelPort`, `BastionAccessPort`.
