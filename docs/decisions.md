# Architectural Decision Records (ADRs)

> This document maintains the persistent, immutable architectural decisions, foundational invariants, and rejected alternatives for **Hexaqueue**. Consult this record before proposing architectural changes to prevent architectural drift across sessions and context compressions.

---

## Index of Architectural Decisions

- [ADR-001: Strict Hexagonal Layer Boundaries & Multi-Package Monorepo Topology](#adr-001-strict-hexagonal-layer-boundaries--multi-package-monorepo-topology)
- [ADR-002: Dual-Implementation Oracle Verification for Job DAGs & State Transitions](#adr-002-dual-implementation-oracle-verification-for-job-dags--state-transitions)
- [ADR-003: Cloud-Agnostic Elasticity & Dollar-Denominated Budget Accounting](#adr-003-cloud-agnostic-elasticity--dollar-denominated-budget-accounting)
- [ADR-004: Anti-Fake-Pass Exercise Gates & Strict Test Symmetry](#adr-004-anti-fake-pass-exercise-gates--strict-test-symmetry)
- [ADR-005: Hexaqual Governance, Gate Audits & Anti-Drift Documentation](#adr-005-hexaqual-governance-gate-audits--anti-drift-documentation)
- [ADR-006: Monorepo PEP 420 Namespace Package Traversal & Single-Pass Distributed CI Slicing](#adr-006-monorepo-pep-420-namespace-package-traversal--single-pass-distributed-ci-slicing)
- [ADR-007: Zero-Trust OpenSSH Confinement and Ephemeral Git Worktree Isolation for Distributed Test Execution](#adr-007-zero-trust-openssh-confinement-and-ephemeral-git-worktree-isolation-for-distributed-test-execution)
- [ADR-008: Elastic Scale-to-Zero Worker Pool Governed by an Always-On Controller](#adr-008-elastic-scale-to-zero-worker-pool-governed-by-an-always-on-controller)

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

---

## ADR-006: Monorepo PEP 420 Namespace Package Traversal & Single-Pass Distributed CI Slicing

### Context
In Python monorepos containing multiple independent subpackages that share standardized internal directory conventions (e.g. `packages/<pkg>/tests/unit/domain/test_models.py`), Pytest's default module resolution stops directory traversal at the first parent folder lacking an `__init__.py`. Because `packages/<pkg>/` is a standalone distribution package rather than an importable sub-package, Pytest defaults to treating `tests` as the top-level package root, assigning all subpackages the identical module path `tests.unit.domain.test_models`. When collecting the entire repository at once, Python caches the first imported module in `sys.modules`, causing Pytest to attribute tests to the wrong subpackage and crash with `(no match in any of [<Module test_models.py>])`.

Additionally, running a separate "distributed test slicing" job in CI alongside standard in-process test runs duplicated test execution cycles without replacing in-process test scheduling.

### Decision
1. **PEP 420 Namespace Package Traversal**:
   - Enforce `consider_namespace_packages = true` in root `pyproject.toml` (`[tool.pytest.ini_options]`). This instructs Pytest to traverse namespace packages through `packages/` to the workspace root, assigning globally unique module names (`packages.<pkg>.tests.unit.domain.test_models`) and eliminating cross-package shadowing.
2. **Worker Command Hardening**:
   - Explicitly pass `"--import-mode=importlib"` and `"-o", "consider_namespace_packages=true"` in `_build_slice_cmd` across all worker providers (local subprocess and container).
3. **Single-Pass CI Dogfooding**:
   - Consolidate CI pipeline execution: `test-suite` cold-boots the local Hexaqueue controller daemon and schedules the entire workspace test suite natively via `uv run hexaqual test run -U --profile ci`, completely replacing duplicate in-process xdist jobs.

### Rejected Alternatives
- *Subpackage-specific test file naming prefixes (e.g. `test_server_models.py`)*: Burdensome and breaks 1:1 test symmetry parity rules enforced by `hexaqual parity test`.
- *Retaining duplicate CI pipeline stages*: Inefficient duplicate resource consumption; running tests exclusively via Hexaqueue guarantees true production dogfooding.

---

## ADR-007: Zero-Trust OpenSSH Confinement and Ephemeral Git Worktree Isolation for Distributed Test Execution

### Context
Distributed test execution in CI/CD pipelines requires running test suites across remote worker nodes (e.g., cloud spot fleets or high-core bare-metal instances). However, allowing CI runners or external clients SSH access with shell or arbitrary command execution privileges presents severe security and stability risks:
1. **Remote Host Mutation**: Ephemeral CI jobs or untrusted PRs could execute malicious commands, mutate system configurations, tamper with host daemons, or alter local code checkouts.
2. **Persistent State Contamination**: Running tests in the repository working directory on a remote node pollutes git tracking, leaves behind uncommitted artifacts and dirty caches, and leads to non-reproducible test flake across runs.
3. **Privilege Creep**: Defaulting to administrative accounts (such as `ubuntu` or root) gives CI runners unnecessary access to system facilities.

### Decision
1. **Zero-Trust OpenSSH Confinement (`hexaqueue-ci`)**:
   - Provision a dedicated, unprivileged system account (`hexaqueue-ci`) with `/bin/false` login shell, no sudo privileges, and zero write permissions to system services or repository roots.
   - Lock down SSH key authentication using OpenSSH `authorized_keys` forced directives:
     ```ssh-config
     command="/bin/false",no-pty,no-agent-forwarding,no-X11-forwarding,permitopen="localhost:8000",permitopen="127.0.0.1:8000" <ci_public_key>
     ```
   - Remote client connections are restricted to local port forwarding (`-L 8000:localhost:8000 -N`). Any attempt to allocate a PTY, execute shell commands, or forward to unauthorized ports fails with exit code 1.
2. **Detached Ephemeral Git Worktree Isolation**:
   - Every distributed test slice executes inside an isolated, ephemeral git worktree created under `/tmp/hexaqueue/runs/<session_id>/slice-<N>` branching from a read-only git object cache.
   - Computations execute on ephemeral disk space without altering the host's primary working tree or git indices.
3. **Guaranteed Teardown & Garbage Collection**:
   - Upon session completion (success, failure, or cancellation), all slice worktrees are forcefully purged (`git worktree remove --force`), ensuring zero state mutation on the host node.
4. **Immutable Controller Plane**:
   - The central Hexaqueue controller daemon runs as a managed system service (systemd) pinned to an immutable release artifact, listening strictly on `localhost:8000`.
5. **Provider-Agnostic Secret & User Standardization**:
   - Standardize on `HEXAQUEUE_CLUSTER_HOST` and `HEXAQUEUE_SSH_USER` (defaulting to `hexaqueue-ci`). Deprecate and drop vendor-specific variables (`OCI_HOST`, `OCI_USER`).

### Rejected Alternatives
- *Direct SSH command execution (`ssh user@host "pytest ..."`)*: Rejected due to catastrophic security exposure and inability to throttle, track, or sandbox remote workloads.
- *Defaulting to administrative accounts (`ubuntu`)*: Rejected under the principle of least privilege; a compromised CI token must never yield root or sudo access.
- *Shared workspace on remote host*: Rejected because concurrent runs or dirty state mutations create non-reproducible test failures.

### ADR-007 Amendment: Worker Ingress on Private VNIC
To enable internal, scale-to-zero pool workers to communicate with the controller without exposing cluster control planes to the public internet, ADR-007 §4 is amended as follows:
- `127.0.0.1:8000`: Client ingress strictly confined to the restricted SSH tunnel from authorized CI runners or local developer shells. Unchanged.
- `<private VNIC IP>:8001`: Internal worker-only API (registration, heartbeats, slice leasing, report aggregation). Reachable strictly within the private VCN via the `worker-nsg`, authenticated via a shared ephemeral pool join token retrieved from OCI Vault using OCI Instance Principals.

---

## ADR-008: Elastic Scale-to-Zero Worker Pool Governed by an Always-On Controller

### Context
Hexaqueue's remote test execution on Oracle Cloud Infrastructure (OCI) previously operated on a single static VM (`129.146.115.79`, A1.Flex 4 OCPU / 24 GB) running 24/7, executing all slices as local subprocesses with workspace collateral persisted on the controller's local disk. While Hexaqueue already defined core elasticity ports (`InstancePoolGovernorPort`, `OciInstancePoolAdapter`, `PresignedStoragePort`, `FreeTierGovernorPort`), this infrastructure did not exercise or dogfood dynamic scaling, multi-node scheduling, or budget accounting in production.

To validate Hexaqueue under authentic production conditions while remaining strictly within the monthly Always-Free allowance (3,000 OCPU-hours and 18,000 GB-hours) on a Pay-As-You-Go (PAYG) or trial account, the cluster must evolve into an elastic, self-managed scale-to-zero architecture governed by an always-on coordinator.

### Decision
1. **Always-On Coordinator Node (1 OCPU / 6 GB)**:
   - Resize the permanent controller VM to 1 OCPU / 6 GB. It acts as the cluster scheduler, lease manager, and local slice worker for single-slice or low-depth runs, ensuring CI never blocks or fails back to local execution if cloud instance pool provisioning fails.
2. **Scale-to-Zero Worker Pool in Private VCN**:
   - Worker nodes are provisioned dynamically in a private VCN subnet (zero public IPs) via OCI Instance Pools governed by `InstancePoolGovernorPort`.
   - Workers boot on demand when queue depth exceeds controller capacity, and scale down to zero after a configurable warm idle period (e.g. 15 minutes).
3. **Object Storage Collateral & Coverage Distribution**:
   - Workspace bundles (CAS collateral) and final coverage artifacts are transferred via OCI Object Storage using short-lived Pre-Authenticated Requests (PARs) via `PresignedStoragePort` and `CollateralServicePort`. Workers never mount shared file systems or require incoming SSH connections.
4. **Pull-Based Slice Scheduling**:
   - Worker nodes authenticate via an instance pool join token read from OCI Vault using instance principals, register with the controller over `<private VNIC IP>:8001`, and long-poll to lease slices. Slices are weighted and leased proportionally to worker OCPUs with heartbeat-based lease expiration and automatic requeueing.
5. **Month-to-Date Hour-Budget Governance**:
   - Budget governance (`FreeTierGovernorPort`) tracks accumulated month-to-date OCPU-hours and GB-hours rather than instantaneous vCPU count. The governor refuses scale-out requests when projected usage approaches the safety-margined monthly free ceiling (~2,270 burst OCPU-h remaining after controller baseline).
6. **Vertical Scaling per Worker Node**:
   - Because Always-Free block storage is capped at 200 GB (~47 GB minimum boot volume per instance = ~4 instances max: 1 controller + 3 workers), bursting capacity scales vertically (larger A1.Flex shapes with 4–8 OCPU per worker) before adding additional worker nodes.
7. **Graceful Fallback on Capacity Errors**:
   - If OCI returns `Out of host capacity`, a provisioning timeout occurs, or the budget governor throttles scale-out, the scheduler automatically dispatches slices back to the controller's local execution runtime.

### Rejected Alternatives
- *Direct SSH Fan-Out to Workers*: Rejected because workers reside in private subnets without public IPs; managing dynamic SSH tunnels to ephemeral worker nodes is fragile and increases latency.
- *Push-Based Work Distribution via Controller-Initiated SSH*: Rejected because it violates ADR-007 least-privilege trust direction and requires baking host SSH keys into images.
- *Object Storage Polling as Queue*: Rejected because polling high-frequency tasks over S3/OCI Object Storage introduces multi-second latency and rapidly exhausts monthly request allowances.
- *Exposing Controller API Publicly*: Rejected because exposing cluster execution control planes to the public internet violates ADR-007 zero-trust boundaries.
- *Static 4 OCPU Always-On VM*: Rejected because it wastes compute budget during idle hours and fails to dogfood Hexaqueue's native autoscaling, state machines, and failover logic.
