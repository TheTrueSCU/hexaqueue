# Architecture & Hexagonal Boundaries

> Hexaqueue decouples core scheduling logic, graph dependency evaluation, storage isolation, and compute runtimes across strict hexagonal layers.

---

## 1. The Hexagonal Golden Rules

1. **Pure Domain Center (`domain/`)**:
   - Zero framework or infrastructure dependencies.
   - Contains pure models (`JobSpec`, `RunSpec`, `ResourceRequirements`), DAG graph validation (`JobDagEngine`), and lifecycle state machines (`compute_run_state`, `compute_run_outcome`).
   - All errors subclass `HexaqueueError`.

2. **Ports as Inversion Boundaries (`ports/`)**:
   - `JobQueuePort`: Abstract task enqueueing, dequeueing, and priority indexing.
   - `SchedulerControllerPort`: Central pipeline submission and status aggregation.
   - `StorageVolumePort`: Isolated scratch storage allocation and ephemeral cleanup.
   - `ExecutionRuntimePort`: Subprocess and containerized process execution.
   - `LogStreamPort`: Chunked stdout/stderr real-time streaming.

3. **Adapters Implement Ports (`adapters/`)**:
   - Translate external protocols (POSIX subprocesses, local memory queues, disk storage, S3/GCS, Kubernetes Kueue) into internal domain contracts.
   - Adapters never import from `infra/`.

4. **Zero-Cost Guard & Native Deference**:
   - Provides software-managed local adapters and provider-native deference adapters.
   - Supports `FREE_TIER` resource clamping for $0 cloud spend developer loops.
