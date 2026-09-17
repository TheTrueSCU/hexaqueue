# CHANGELOG

## v0.3.0 (2026-09-17)

### Highlights & Features
* **CLI Output Formatting Alignment (`hexaqueue-cli`)**:
  * Unified `-f` / `--format` flag supporting `table`, `json`, `markdown`, `plain`, and `rich` formats.
  * Standardized `CliPresenter` handling tabular and tree formatting with column truncation and ANSI auto-stripping in non-interactive terminals.
  * Aligned `--format` across `hq run submit`, `hq run list`, `hq workflow submit`, `hq workflow status`, and `hq workflow list`.
* **Distributed Split/Join Barrier Resolution (`hexaqueue-workflow`)**:
  * Implemented `SplitJoinBarrierPort` and `GrpcSplitJoinBarrierAdapter` integrating `hexastack-grpc` with `hexaflow>=0.3.0` dynamic steps (`@wf.map_step`).
  * Added partition state tracking (`BarrierPartition`, `BarrierResolutionSummary`, `BarrierState`) with sub-step fan-out, dynamic parallel execution, and barrier checkpoint synchronization.
  * Robust error propagation and partial partition recovery inside `HexaqueueDistributedEngine`.
* **Hypothesis State Machine Fuzzing for Job Preemption (`hexaqueue-core`)**:
  * Implemented `JobPreemptionStateMachine` modeling arbitrary transitions across `SUBMITTED`, `PENDING`, `RUNNING`, and `DONE` states with preemption signals (`TerminalOutcome.PREEMPTED`).
  * Validated checkpoint state preservation and re-queue recovery invariants across spot termination and cluster preemption events.
  * Verified pure mathematical roll-up of `compute_run_state` and `compute_run_outcome`.
* **Dependency & Ecosystem Upgrades**:
  * Upgraded dependencies to `hexastack-*>=0.6.0`, `hexaflow>=0.3.0`, and `hexaqual[all]>=0.4.0`.
  * Synchronized workspace and all 13 subpackages to `v0.3.0`.

## v0.2.0 (2026-09-16)

### Highlights & Features
* **Native Hexaflow Cluster Scheduler Adapter (`hexaqueue-workflow`)**:
  * Implemented `HexaqueueDistributedEngine` conforming to `hexaflow.ports.WorkflowEnginePort` for executing workflows across distributed Hexaqueue worker clusters.
  * Supports lifecycle controls: `run`, `run_async`, `resume`, `resume_async`, `restart`, `restart_async`, `abort`, and `abort_async`.
  * Support for DAG split stage concurrent job dispatches (`CONCURRENT_ALL`, `CONCURRENT_FAIL_FAST`), checkpoint persistence, and automatic reverse compensation unwinding.
* **Distributed Artifact Staging via StoragePort**:
  * Added `StoragePortArtifactStagingAdapter` implementing `ArtifactStagingPort` using `hexastack_core.ports.storage.StoragePort`.
  * Configurable payload offloading (>64KB threshold) with SHA256 integrity digest verification, JSON serialization, and pickle fallback.
  * Preserves `ArtifactReference` envelopes inside `CheckpointRecord.output_payload` for transparent restoration across distributed worker nodes.
* **CLI Workflow Management Subcommands (`hq workflow`)**:
  * Added `hq workflow submit` for declarative workflow YAML submission with custom parameters and execution monitoring.
  * Added `hq workflow status` for run inspection, phase tracking, and step duration diagnostics.
  * Added `hq workflow resume` and `hq workflow abort` for interactive distributed workflow lifecycle control.
* **Governance & Quality Gates**:
  * Upgraded workspace to consume standardized `hexaqual` pre-commit hooks (`hexaqual-sanity`, `hexaqual-architecture`).
  * Full hexagonal boundary isolation with zero leaks from `infra/` to `adapters/`.
  * Maintained >90% test coverage across all workflow and CLI components with 100% unit test parity.

## v0.1.0 (2026-09-07)

### Highlights & Features
* **Modular Monorepo Architecture**: 13 cohesive, decoupled hexagonal architecture packages (`hexaqueue-core`, `hexaqueue-cli`, `hexaqueue-server`, `hexaqueue-worker`, `hexaqueue-collateral`, `hexaqueue-scanner`, `hexaqueue-monitor`, `hexaqueue-dashboard`, `hexaqueue-github-runner`, `hexaqueue-gitlab-runner`, `hexaqueue-kueue`, `hexaqueue-workflow`, and `hexaqueue` umbrella).
* **Core Kernel & State Machine Rollup**: Deterministic state progression for leaf jobs (`SUBMITTED` -> `BLOCKED` -> `PENDING` -> `RUNNING` -> `DONE`) and aggregated root runs (`SUBMITTED`, `BLOCKED`, `RUNNING`, `DONE`) with terminal outcomes (`COMPLETED`, `FAILED`, `CANCELLED`, `TIMED_OUT`, `PREEMPTED`).
* **DAG Dependency & Cycle Engine**: Kahn's algorithm topological sorting with cycle detection and rich edge trigger rules (`AFTER_OK`, `AFTER_NOT_OK`, `AFTER_ANY`, `AFTER_CORR`).
* **Hierarchical Job Groups & Parameter Sweeps**: Arbitrary recursive group nesting with variable inheritance, template interpolation (`{{ var }}`), explicit sequences (`params`), and Cartesian product matrix sweeps (`matrix`).
* **Content-Addressable Collateral (CAS)**: Local filesystem CAS staging at `~/.hexaqueue/collateral` with streaming SHA256 integrity verification, quarantine states, and automatic retention tiers.
* **Hexagonal Ports & Zero-Cost Developer Loop**: Comprehensive abstract port interfaces for queueing, runtime execution, isolated storage, budget accounting, and log streaming with zero-dependency local adapters and `FREE_TIER` resource clamping ($0 cloud spend).
* **Realistic Example Applications**: End-to-end batch ETL pipeline (`examples/data-pipeline`) and stochastic multi-regime Monte Carlo simulation (`examples/monte-carlo`) with programmatic Python DAG builders and CLI collateral scripts.
* **Developer Experience CLI (`hq`)**: Local developer commands for run submission, status monitoring, and log streaming.
* **360° Quality Rigor**: >90% branch test coverage, Google-style docstrings with `Notes/Architectural Intent:`, 1:1 unit test parity enforcement, Hypothesis property-based fuzzing, and hardened multi-tier CI/CD pipelines.
