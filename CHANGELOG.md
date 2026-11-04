# CHANGELOG

## v0.8.1 (2026-11-04)

### Standalone CLI Packaging & Composite Action Hardening
* **Standalone CLI Dependency & Entrypoint Completeness (`hexaqueue`, `hexaqueue-core`, `hexaqueue-server`)**:
  * Added `[project.scripts]` (`hq` and `hexaqueue`) directly to the umbrella `hexaqueue` package so `uv tool install hexaqueue` and standalone runner installations expose the `hq` CLI entrypoint natively.
  * Added `hypothesis>=6.100.0` to `hexaqueue-core` runtime dependencies and `greenlet>=3.0.0` to `hexaqueue-server` runtime dependencies so standalone `hq cluster discover` and `hq cluster tunnel` invocations execute cleanly in minimal non-dev runner environments.
* **Composite GitHub Action Hardening (`action.yml`)**:
  * Added automatic `.env` variable export to `$GITHUB_ENV` (excluding raw base64 private keys) so `HEXAQUEUE_CLUSTER_HOST` and `HEXAQUEUE_SSH_USER` propagate to subsequent workflow steps.
  * Exported both `kebab-case` (`cluster-ready`, `cluster-host`) and `snake_case` (`cluster_ready`, `cluster_host`) composite action outputs for downstream job compatibility.
  * Ensured `$HOME/.local/bin` and `$PWD/.venv/bin` are appended to `$GITHUB_PATH` and active step `PATH`.

## v0.8.0 (2026-11-04)

### Composite GitHub Action & CAS Collateral Workspace Transport
* **Zero-Checkout CAS Collateral Workspace Packaging (`pytest-hexaqueue`, `hexaqueue-server`)**:
  * Decoupled test runner client environments from remote controller git worktrees: client workspaces package code-under-test into content-addressable `.tar.gz` archives and upload directly to `/collateral/stage`.
  * Implemented pluggable workspace archivers (`GitWorkspaceArchiver` via `git ls-files` with safety exclusions and metadata normalization, and `GenericWorkspaceArchiver` supporting `.gitignore` and `.ignore` path specs).
  * Added SHA-256 header validation, deduplication hit caching, and safe extraction with `filter="data"` on `hexaqueue-server`.
* **Turnkey Composite GitHub Action (`action.yml`)**:
  * Authored turnkey composite action `TheTrueSCU/hexaqueue` supporting environment secret hydration (`cluster-env`), zero-trust SSH tunneling (`auto-tunnel`), probe stages (`probe-only`), and interactive summary reporting (`step-summary`).
  * Converted `hexaqueue`'s own CI workflows to dogfood `uses: ./` across reachability probing and distributed test runs.
* **Security & Governance Invariants**:
  * Defaulted `LocalCollateralServiceAdapter` quarantine adapter to `NoOpSecurityQuarantineAdapter` for zero-trust private runner CI.
  * Preserved full test symmetry and 1:1 test parity across all newly authored port and adapter modules.

## v0.7.0 (2026-11-03)

### Zero-Trust Ephemeral Test Cloud Slicing & Security Hardening
* **Zero-Trust OpenSSH Confinement & Identity Isolation (`ADR-007`, `hexaqueue-core`, `hexaqueue-cli`)**:
  * Provisioned dedicated, unprivileged system account (`hexaqueue-ci`) with `/bin/false` login shell, no sudo privileges, and locked `authorized_keys` forced directives (`command="/bin/false",permitopen="localhost:8000"`).
  * Completely eliminated vendor-specific `OCI_HOST` and `OCI_USER` across runner configurations, default profiles, and CLI tools, standardizing on provider-agnostic `HEXAQUEUE_CLUSTER_HOST` and `HEXAQUEUE_SSH_USER`.
  * Removed all fallback defaults to administrative or generic accounts (`ubuntu`), enforcing least-privilege zero-trust access across CI and distributed runner profiles.
* **Ephemeral Git Worktree Isolation & Guaranteed Teardown (`pytest-hexaqueue`)**:
  * Isolated all distributed test slice executions inside dedicated, detached git worktrees under `/tmp/hexaqueue/runs/<session_id>/slice-<N>` branching from an immutable read-only cache.
  * Guaranteed 100% worktree purge and garbage collection upon session completion with zero state mutation on remote host nodes.
* **Hybrid Slicing Partitioning Engine (`pytest-hexaqueue`)**:
  * Added `--hq-local-slices` and `--hq-remote-slices` flags (and corresponding `local_slices` and `remote_slices` configuration profile options) enabling concurrent local and cloud test execution.
  * Supported dynamic automatic scaling via `auto` keyword: dedicating $\max(1, \text{cpu\_count} - 2)$ cores locally while over-partitioning $\max(4, \min(32, \text{tests} // 30))$ slices remotely for queue saturation.
  * Added `--hq-hybrid` flag for turnkey dual-plane local + cloud concurrent execution.
* **GitHub Actions CI Observability & Automated Fleet Reporting (`.github/workflows/ci.yml`)**:
  * Added dynamic Hexaqueue Fleet Discovery summary table to `$GITHUB_STEP_SUMMARY` during cluster probing.
  * Added automated `junit.xml` test execution analytics dashboard reporting engine type, test counts, outcomes, and aggregated duration to `$GITHUB_STEP_SUMMARY`.
  * Added topology diagram verification gate to enforce synchronization of architecture assets.
* **Architecture Topologies & Visual Governance (`scripts/docs/generate_topologies.py`)**:
  * Added `generate_ephemeral_cloud_slicing_diagram()` and rendered `docs/assets/topologies/ephemeral_cloud_slicing.png`.
  * Documented Section 4 in `docs/architecture.md` and updated `docs/guides/pytest-distributed-execution.md` with complete hybrid slicing matrix.

## v0.6.0 (2026-11-01)

### Features & Infrastructure Dogfooding
* **Native CI Dogfooding & Single-Pass Test Execution (`.github/workflows/ci.yml`)**:
  * Consolidated CI pipeline to natively schedule the entire unit and integration test suite (1,075 tests) via Hexaqueue (`--profile ci`), eliminating duplicate pipeline stages.
  * Verified 33% faster wall-clock execution (21.01s vs. 31.44s) compared to default `pytest-xdist -n 2` on standard 2-vCPU GitHub Actions runners due to reduced IPC scheduler lock contention.
* **Monorepo PEP 420 Namespace Package Traversal (`pyproject.toml`, `hexaqueue-server`)**:
  * Added `consider_namespace_packages = true` in `[tool.pytest.ini_options]` to prevent cross-package module shadowing across identical domain test filenames (`test_models.py`).
  * Hardened `_build_slice_cmd` across local subprocess and container workers to explicitly pass `"--import-mode=importlib"` and `"-o", "consider_namespace_packages=true"`.
* **Runner Profile Parity & Auto-Activation (`pytest-hexaqueue`)**:
  * Added `--profile` as a first-class alias for `--hq-profile` matching `hexaqual test run --profile <name>` conventions.
  * Supported implicit Hexaqueue activation whenever a named profile is supplied (`--profile` or `--hq-profile`).
* **Security & Vulnerability Remediation**:
  * Upgraded `opentelemetry-api` to `1.45.2` in `examples/monte-carlo`, remediating CVE-2026-114603 / Dependabot Alert #35.
  * Resolved CodeQL note Alert #79 in `pytest-hexaqueue` test infrastructure.
* **Ecosystem Upgrade**:
  * Upgraded workspace dev dependencies to official `hexaqual[all]>=0.10.0` from PyPI.

## v0.5.0 (2026-10-08)

### Security Audit Remediation & Hardening
* **Positive Administrative Elevation & Principle of Least Privilege (`hexaqueue-server`, `hexaqueue-dashboard`, `hexaqueue-cli`)**:
  * Enforced server-side validation of `HEXAQUEUE_ADMIN_TOKEN` when administrative elevation is asserted via `X-Hexaqueue-Elevate: true` or query parameters.
  * Bound `user_id` and elevation states strictly from authenticated context (`auth`), preventing request-body forgery and privilege escalation.
  * Removed unauthenticated `user_id != "default"` short-circuit bypasses across `handle_cancel_run`, `handle_get_run_status`, `handle_get_job`, `handle_list_jobs`, and `handle_get_logs`.
  * Added mandatory `--admin` flag requirement for privileged CLI commands (`hq exec`, `hq attach`).
* **OpenSSF Scorecard & Gold Policy Compliance**:
  * Remediated OpenSSF Scorecard high alert on `.github/workflows/docs.yml` (`DangerousWorkflowID` / untrusted `workflow_run` artifact download) by triggering directly on `push` to `main` with paths filter.
  * Added root `SECURITY.md` defining supported version matrix, coordinated disclosure SLA (90-day window, 48-hour critical acknowledgement), threat model, trust boundaries, and SLSA provenance guarantees.
  * Consolidated `.github/dependabot.yml` to native `uv` package ecosystem management.
* **Collateral Staging & Quarantine Hardening (`hexaqueue-collateral`, `hexaqueue-scanner`)**:
  * Enforced strict path traversal rejection (blocking `..`, `/`, `\`, and absolute paths) in `IngestionRequest.validate_invariants` and staging directory path resolution in `LocalCollateralServiceAdapter`.
  * Hardened `CompositeQuarantineScannerAdapter` and `LocalCollateralServiceAdapter` to fail closed with `CollateralState.QUARANTINED` when no scanning engines are operational or configured.
  * Surfaced rule compilation syntax errors in `YaraRuleScannerAdapter` rather than silently degrading to fallback heuristics.
* **Worker & Distributed Engine Integrity (`hexaqueue-worker`, `hexaqueue-workflow`)**:
  * Isolated scratch directory cleanup in a `finally` block in `LocalSubprocessRuntimeAdapter` to guarantee cleanup and prevent GPU capacity leakage on process failure.
  * Fixed intra-stage step barriers in `HexaqueueDistributedEngine` to resolve and await actual task futures rather than unawaited stage coroutines.
  * Wired `LocalStorageAdapter` for durable artifact staging across CLI workflow invocations.
* **Scheduler Algorithmic Corrections (`hexaqueue-core`, `examples/monopoly`)**:
  * Fixed conservative anchor slot allocation and dynamic backfill window adjustments to correctly reflect available capacity and start time horizons.
  * Bound slot allocation in monopoly simulation to configured tenant `job_count` and honored `checkpointable` configuration.
* **Static Analysis & CodeQL Resolutions**:
  * Resolved 15 active CodeQL alerts across `dag.py`, `explainability.py`, `notification.py`, `cgroups.py`, `broadcast.py`, `local.py`, `pty.py`, `telemetry.py`, and `main.py`.
* **Ecosystem Alignment & Secondary Port Contract Streamlining**:
  * Upgraded workspace dependencies across all subpackages to `hexastack-*>=0.8.0`, `hexaflow>=0.4.1`, and `hexaqual[all]>=0.9.1`.
  * Streamlined `NotificationDispatcher` in `hexaqueue-core` to directly invoke the modern `NotificationPort.notify(..., targets=...)` signature from `hexastack-core 0.8.0` without legacy fallback overhead.

## v0.4.0 (2026-09-20)

### Highlights & Features
* **Comprehensive CLI Expansion & Administrative Elevation (`hexaqueue-cli`)**:
  * Positive administrative elevation (`--admin`) required for privileged and destructive operations (`hq cancel`, `hq purge`, `hq workers drain`, `hq worker kill`).
  * Added `hq why` explainability command inspecting root-cause waiting reasons and placement barriers.
  * Added `hq top` real-time cluster telemetry console and interactive operator dashboard.
  * Added `hq schedule` cron/interval management, `hq workers` pool inspection, and `hq node` status commands.
  * Standardized surface parity and Rich formatting across all CLI subcommands.
* **Cron, Interval & One-Shot Scheduling Engine (`hexaqueue-server`, `hexaqueue-core`)**:
  * Persistent cron, interval, and deferred one-shot workload dispatchers.
  * Misfire grace period handling, overlapping execution guards, and dynamic schedule lifecycle management.
* **Dynamic Worker Pools, Autoscale & Draining (`hexaqueue-worker`, `hexaqueue-server`)**:
  * Coordinated worker heartbeats, dynamic worker pool autoscaling, and graceful node draining.
  * Workload eviction and reassignment on spot preemption or worker health failure.
* **Real-Time SSE Log Streaming & Multiplexing (`hexaqueue-server`, `hexaqueue-cli`)**:
  * Server-Sent Events (SSE) log streaming adapter with multi-consumer channel multiplexing.
  * Live log tailing in the CLI via `hq logs --follow` with zero-delay chunk buffering.
* **Containerized Execution Adapters (`hexaqueue-worker`)**:
  * Pluggable container execution adapters for Docker, Podman, and Apptainer (Singularity).
  * Enforced container rootless execution, user namespace mapping, and volume isolation.
* **Vulnerability & Security Gate Scanner (`hexaqueue-scanner`)**:
  * Integrated Trivy and Grype static vulnerability and secret analysis adapters.
  * Automated security gating blocking compromised images and non-compliant execution collateral.
* **Free-Tier Limits & Resource Clamping (`hexaqueue-core`)**:
  * Enforced CPU, memory, and concurrency rate limits for unprivileged free-tier tenants.
  * Clamped budget accounting preventing multi-tenant resource starvation.
* **Universal Agent Guardrails Integration**:
  * Upgraded governance engine to `hexaqual>=0.5.0` with universal `.agents/` rules, workflows, and skills synchronization.
  * Configured positive administrative elevation rule (`.agents/rules/hexaqueue-elevation.md`).

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
