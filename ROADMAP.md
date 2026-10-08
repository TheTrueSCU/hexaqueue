# Hexaqueue Public Roadmap

This document outlines the strategic priorities, upcoming milestones, and architectural roadmap for **Hexaqueue** — the Cloud-Agnostic HPC Batch Scheduler and Distributed Job Orchestrator.

---

## Completed Milestones

### v0.1.0 (Core Kernel, Local Runner & Complete Local Loop)
- [x] **Core Lifecycle & State Machines**: Strict state machine transitions for `JobState`, `RunState`, and `TerminalOutcome` (`hexaqueue-core` - Issue #1).
- [x] **Content-Addressable Collateral Pipeline**: `CollateralBundle` invariants, quarantine states, and retention tiers (`hexaqueue-core` - Issue #2).
- [x] **DAG Dependency Engine**: Topological sorting via Kahn's algorithm, O(V+E) cycle detection, and trigger condition evaluations (`AFTER_OK`, `AFTER_NOT_OK`, `AFTER_ANY`, `AFTER_CORR`) (`hexaqueue-core` - Issue #3).
- [x] **Hexagonal Port Contracts**: Abstract interfaces for `StorageVolumePort`, `ExecutionRuntimePort`, `JobQueuePort`, `LogStreamPort`, `SecurityQuarantinePort`, `BudgetAccountingPort`, and `ComputeResourcePort` (`hexaqueue-core` - Issue #4).
- [x] **Standardized In-Memory & Local Adapters**: Zero-dependency mock & local adapters in dedicated subdirectories (`hexaqueue-core` - Issue #25).
- [x] **Direct-to-Disk Collateral Staging & Ingestion**: Local filesystem CAS staging at `~/.hexaqueue/collateral` with streaming SHA256 integrity verification (`hexaqueue-collateral` - Issue #26).
- [x] **Standalone In-Process Scheduler Controller**: Central dispatcher loop coordinating in-memory priority queues and DAG prerequisites (`hexaqueue-server` - Issue #27).
- [x] **Local Subprocess Worker Execution Daemon**: Compute worker managing scratch directory lifecycles and POSIX process isolation (`hexaqueue-worker` - Issue #28).
- [x] **Developer Experience CLI (`hq`)**: Local developer commands (`hq run submit`, `hq status`, `hq list`, `hq logs -f`, `hq cancel`) (`hexaqueue-cli` - Issue #29).
- [x] **Hierarchical Suite & Parameter Matrix Compiler**: Cartesian product parameter sweeps with recursive variable interpolation (`hexaqueue-core` - Issue #13).

### v0.2.0 (Hexaflow Integration & Distributed Engine)
- [x] **Hexaflow Cluster Scheduler Adapter**: `HexaqueueDistributedEngine` implementing `hexaflow.ports.WorkflowEnginePort` (`hexaqueue-workflow`).
- [x] **Distributed Artifact Staging**: Large payload offloading via `StoragePort` with SHA-256 integrity digests (`hexaqueue-workflow`).
- [x] **CLI Workflow Management**: Declarative workflow submission, status inspection, resume, and abort subcommands (`hexaqueue-cli`).

### v0.3.0 (Distributed Barrier Resolution & CLI Formatting Alignment)
- [x] **CLI Output Formatting Alignment**: Standardized `-f` / `--format` flag (`table`, `json`, `markdown`, `plain`, `rich`) and `CliPresenter` across commands (`hexaqueue-cli`).
- [x] **Distributed Split/Join Barrier Resolution**: `SplitJoinBarrierPort` and `GrpcSplitJoinBarrierAdapter` integrating `hexastack-grpc` with `hexaflow>=0.3.0` dynamic mapped steps (`@wf.map_step`) (`hexaqueue-workflow`).
- [x] **Hypothesis Preemption State Machine Fuzzing**: Rule-based stateful fuzzing verifying lifecycle invariants, preemption recovery, and checkpoint preservation (`hexaqueue-core`).
- [x] **Ecosystem Dependency Synchronization**: Upgraded to `hexastack-*>=0.6.0`, `hexaflow>=0.3.0`, and `hexaqual>=0.4.0`.

### v0.4.0 (CLI Expansion, Schedulers & Resource Clamping)
- [x] **Comprehensive CLI Expansion & Administrative Elevation**: Positive elevation (`--admin`) required for privileged commands (`hq cancel`, `hq purge`, `hq workers drain`), plus `hq why` explainability and `hq top` telemetry (`hexaqueue-cli`).
- [x] **Cron, Interval & One-Shot Scheduling Engine**: Persistent cron, interval, and deferred one-shot workload dispatchers with misfire grace periods and overlap guards (`hexaqueue-server`, `hexaqueue-core`).
- [x] **Dynamic Worker Pools, Autoscale & Draining**: Coordinated worker heartbeats, dynamic worker pool autoscaling, and graceful node draining on spot preemption (`hexaqueue-worker`, `hexaqueue-server`).
- [x] **Real-Time SSE Log Streaming & Multiplexing**: Server-Sent Events (SSE) log streaming adapter with multi-consumer channel multiplexing and live CLI tailing (`hexaqueue-server`, `hexaqueue-cli`).
- [x] **Containerized Execution Adapters**: Rootless Podman OCI and Apptainer/Singularity HPC execution runtimes with GPU passthrough (`hexaqueue-worker`).
- [x] **Vulnerability & Security Gate Scanner**: Integrated Trivy and Grype static vulnerability and secret analysis adapters (`hexaqueue-scanner`).
- [x] **Free-Tier Limits & Resource Clamping**: CPU, memory, and concurrency rate limits clamping unprivileged free-tier tenants (`hexaqueue-core`).
- [x] **Universal Agent Guardrails Integration**: Synchronized universal `.agents/` rules, workflows, and skills via `hexaqual>=0.5.0`.

### v0.5.0 (Security Audit Remediation, Governance & Ecosystem Hardening)
- [x] **OpenSSF Scorecard & Gold Policy Compliance**: Remediated `DangerousWorkflowID` alert in docs workflow; added root `SECURITY.md` defining SLA, threat model, trust boundaries, and SLSA provenance guarantees.
- [x] **Positive Administrative Elevation & Auth Hardening**: Bound `user_id` and elevation states strictly from authenticated context; validated `HEXAQUEUE_ADMIN_TOKEN`; required `--admin` on `hq exec` and `hq attach` (`hexaqueue-server`, `hexaqueue-dashboard`, `hexaqueue-cli`).
- [x] **Collateral Staging & Quarantine Hardening**: Enforced strict path traversal rejection (`..`, `/`, `\`); hardened composite and local collateral adapters to fail closed with `CollateralState.QUARANTINED` (`hexaqueue-collateral`, `hexaqueue-scanner`).
- [x] **Worker & Distributed Engine Integrity**: Isolated scratch directory cleanup in `finally` block preventing GPU memory leaks; fixed intra-stage step barriers to await actual task futures (`hexaqueue-worker`, `hexaqueue-workflow`).
- [x] **Scheduler Algorithmic Corrections**: Fixed conservative anchor slot allocation and dynamic backfill window calculations; bound monopoly simulation slots to configured tenant limits (`hexaqueue-core`, `examples/monopoly`).
- [x] **Static Analysis & CodeQL Resolutions**: Resolved 15 active CodeQL alerts across core, server, and worker packages.
- [x] **Ecosystem Lockstep Alignment**: Upgraded all workspace subpackages to `hexastack-*>=0.8.0`, `hexaflow>=0.4.1`, and `hexaqual[all]>=0.9.1`.
- [x] **Secondary Notification Port Contract Streamlining**: Direct delegation to modern `NotificationPort.notify(..., targets=...)` signature from `hexastack-core 0.8.0` (`hexaqueue-core`).

---

## 🎯 Active Milestone: v0.6.0 (Cloud Deference, Multi-Cloud Ingestion & Kubernetes Kueue Bridge)
- [ ] **Direct Multi-Part Presigned S3/GCS Ingestion**: Zero-payload control plane direct uploads with pre-signed chunked URLs (`hexaqueue-collateral` - Issue #5).
- [ ] **Provider-Native Deference & No-Op Bypass**: Direct batch submission to AWS Batch, GCP Batch, and Azure CycleCloud (`hexaqueue-worker`).
- [ ] **Kubernetes Batch v1 & Kueue Bridge**: Cloud-native Kueue admission controller integration (`hexaqueue-kueue`).
- [ ] **High-Availability Controller & Leader Election**: Distributed HA scheduler clustering backed by Raft and Etcd (`hexaqueue-server` - Issue #7).
- [ ] **Controlled Fair-Share Preemption**: 100-slot monopoly fairness algorithms with 30–60s `SIGUSR1` checkpointing (`hexaqueue-server`).

---

## 🔮 Upcoming Milestones

### v0.7.0 (Ecosystem CI Drivers, Zero-Trust Architecture & Web Portal)
- [ ] **CI/CD Ephemeral Runner Drivers**: GitHub Actions JIT ephemeral runner bridge (`hexaqueue-github-runner` - Issue #22) and GitLab CI custom executor (`hexaqueue-gitlab-runner` - Issue #23).
- [ ] **Zero-Trust Security Architecture**: SPIFFE/SPIRE workload attestation, KMS envelope encryption, and mutual TLS 1.3 (`hexaqueue-core` - Issue #19).
- [ ] **Cloud-Agnostic Bastion & Operator Access Protocol**: Abstract `BastionAccessPort` and cloud session adapters (`hexaqueue-core` - Issue #18).
- [ ] **Reactive Web Portal & Operator Console**: Live job inspector, DAG visualizer, and audit portal (`hexaqueue-dashboard` - Issue #12).
