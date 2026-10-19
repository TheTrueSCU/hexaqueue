# Architectural Decision Records (ADRs)

> This document maintains the persistent, immutable architectural decisions, foundational invariants, and rejected alternatives for **Hexaqueue**. Consult this record before proposing architectural changes to prevent architectural drift across sessions and context compressions.

---

## Index of Architectural Decisions

- [ADR-001: Strict Hexagonal Layer Boundaries & Multi-Package Monorepo Topology](#adr-001-strict-hexagonal-layer-boundaries--multi-package-monorepo-topology)
- [ADR-002: Dual-Implementation Oracle Verification for Job DAGs & State Transitions](#adr-002-dual-implementation-oracle-verification-for-job-dags--state-transitions)
- [ADR-003: Cloud-Agnostic Elasticity & Dollar-Denominated Budget Accounting](#adr-003-cloud-agnostic-elasticity--dollar-denominated-budget-accounting)
- [ADR-004: Anti-Fake-Pass Exercise Gates & Strict Test Symmetry](#adr-004-anti-fake-pass-exercise-gates--strict-test-symmetry)
- [ADR-005: Hexaqual Governance, Gate Audits & Anti-Drift Documentation](#adr-005-hexaqual-governance-gate-audits--anti-drift-documentation)

---

## ADR-001: Strict Hexagonal Layer Boundaries & Multi-Package Monorepo Topology

### Context
Hexaqueue is a cloud-agnostic HPC batch scheduler and distributed job orchestrator modernizing traditional HPC schedulers (LSF, SGE, Slurm) with cloud-native elasticity. Because the system supports varied execution planes (local workstations, rootless OCI containers, Kubernetes Kueue, AWS/GCP Batch deference), mixing infrastructure dependencies into scheduling and DAG evaluation logic creates tight coupling and makes local hermetic testing impossible.

### Decision
1. **Pure Domain Center (`domain/`)**:
   - Zero framework, runtime, or infrastructure dependencies.
   - Contains pure data models (`JobSpec`, `RunSpec`, `ResourceRequirements`), acyclic graph evaluation (`JobDagEngine`), parameter matrix compilers (`GroupExpansionEngine`), and lifecycle state machines (`compute_run_state`, `compute_run_outcome`).
   - Domain logic must remain synchronous and deterministic wherever possible.
   - All domain exceptions inherit from `HexaqueueError`.
2. **Ports as Inversion Boundaries (`ports/`)**:
   - `JobQueuePort`: Abstract task enqueueing, dequeueing, and priority indexing.
   - `SchedulerControllerPort`: Central pipeline submission and status aggregation.
   - `StorageVolumePort`: Isolated scratch storage allocation and ephemeral cleanup.
   - `ExecutionRuntimePort`: Subprocess and containerized process execution.
   - `BudgetAccountingPort`: Real-time dollar-denominated budget tracking, burn rate caps, and spot instance arbitration.
   - `LogStreamPort`: Chunked stdout/stderr real-time streaming.
3. **Adapters Implement Ports (`adapters/`)**:
   - External transports and runtimes (POSIX subprocesses, in-memory queues, Redis, K8s Kueue, S3/GCS) implement ports. Adapters never import from `infra/` or sibling adapters.
4. **Enforcement**:
   - Strict layer boundaries are continuously validated via `import-linter` contracts (`.importlinter`) and `hexaqual parity architecture`.

### Rejected Alternatives
- *Direct Kubernetes / Redis coupling in domain logic*: Rejected because it destroys local $0-spend offline development and makes unit testing require live infrastructure.
- *Single Monolithic Package*: Rejected in favor of explicit modular packages (`hexaqueue-core`, `hexaqueue-worker`, `hexaqueue-server`, `hexaqueue-kueue`, etc.) with clear workspace dependency graphs.

---

## ADR-002: Dual-Implementation Oracle Verification for Job DAGs & State Transitions

### Context
HPC scheduling and workflow DAGs must execute dependency trees (e.g. `AFTER_OK`, `AFTER_NOT_OK`, array job expansions) without deadlocks or missed runs. Subtle corner cases in graph topological sorting or state transition handling cause hung clusters and silent execution drops.

### Decision
1. **Hypothesis Property-Based State Machine Testing**:
   - Complex state transitions and graph topological ordering are verified using Hypothesis state machines.
2. **Dual-Implementation Oracle Verification**:
   - Optimized graph evaluation and scheduling algorithms are cross-evaluated against naive, mathematically verifiable reference graph models ($f_{\text{prod}}(x) \equiv f_{\text{oracle}}(x)$).
3. **Property Verification in CI**:
   - Property tests run in `Stage 3: hypothesis-fuzzing` on pull requests to catch edge-case regressions before merge.

### Rejected Alternatives
- *Unit-test-only verification*: Standard hand-crafted unit tests test known happy paths and miss boundary cycles in dynamic DAG generation.

---

## ADR-003: Cloud-Agnostic Elasticity & Dollar-Denominated Budget Accounting

### Context
Traditional HPC schedulers operate on static, permanently provisioned clusters with fixed node counts, resulting in high idle costs or long wait queues. Conversely, naive cloud elasticity can cause runaway cloud bills.

### Decision
1. **Scale-to-Zero and Scale-from-Zero**:
   - Compute runtimes spin up on demand (via `hexaqueue-kueue`, Kubernetes cluster autoscaling, Karpenter, or cloud batch fleets) and terminate immediately when queues drain.
2. **Dollar-Denominated Budget Guards (`BudgetAccountingPort`)**:
   - Workloads and tenant projects enforce real-time dollar-denominated budget tracking and burn-rate caps.
   - When budgets approach limits, the scheduler automatically shifts workloads to Spot/Preemptible instances or local workstation runtimes ($0 cloud spend developer loops).
3. **Hermetic Collateral Volumes**:
   - Fragile, shared network mounts (NFS) are replaced with content-addressable collateral isolation (`hexaqueue-collateral`) and rootless container mounts.

### Rejected Alternatives
- *Static cluster over-provisioning*: Inefficient and expensive in modern hybrid and multi-cloud environments.
- *Unconstrained auto-scaling without financial governance*: High risk of accidental runaway cloud spending.

---

## ADR-004: Anti-Fake-Pass Exercise Gates & Strict Test Symmetry

### Context
CI suites that silently pass when 0 tests are executed or when assertion statements have side effects undermine software reliability.

### Decision
1. **Anti-Fake-Pass Exercise Gate**:
   - The test runner enforces non-zero test execution. Tests matching filter criteria must exist and execute; passing an empty suite is an error unless `--allow-empty` is explicitly passed.
2. **1:1 Test Symmetry Parity**:
   - Every production module in `packages/<pkg>/src/` requires a matching `packages/<pkg>/tests/unit/` test file and `__init__.py`.
   - Verified via `hexaqual parity test` during `hexaqual sanity`.
3. **Side-Effect-Free Test Assertions**:
   - Return values must be bound to variables prior to assertions (e.g., `result = queue.pop(); assert result is not None`) to satisfy static analysis and CodeQL rules.

### Rejected Alternatives
- *Allowing empty test passes in CI*: Masks test configuration errors and misnamed glob patterns.

---

## ADR-005: Hexaqual Governance, Gate Audits & Anti-Drift Documentation

### Context
Documentation and quality gates frequently drift over time as packages evolve, resulting in outdated references, silent gate skipping, and AI context amnesia.

### Decision
1. **Pinned Composite Actions**:
   - All CI workflows use immutable commit SHAs for composite actions (`TheTrueSCU/hexaqual@7de5ade62e96ac7623b5ec649997e562eea2822d # v0.9.3`).
2. **Automated Quality Gate Auditing**:
   - Every CI quality gate run executes `uv run hexaqual sanity --audit-gates`, verifying that all 10 canonical gates remain active.
3. **Anti-Drift Documentation Linter**:
   - CI executes `uv run hexaqual docs drift` to ensure package counts, versions, and CLI flags described in documentation stay synchronized with code.
4. **AI Agent Re-Anchoring**:
   - `hexaqual-reanchoring.md` is synced into `.agents/rules/` and re-anchors coding assistants against `docs/decisions.md` upon context compaction or architectural proposals.

### Rejected Alternatives
- *Manual gate verification*: Prone to human error and silent gate attrition.
- *Mutable action tags (`@main`, `@v0`) in CI*: Vulnerable to supply-chain attacks and breaking upstream changes.
