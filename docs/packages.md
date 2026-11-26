# Packages Catalog

> Hexaqueue is organized as a modular monorepo of specialized packages that can be installed individually or consumed as a unified orchestrator via `pip install hexaqueue`.

---

| Package | Purpose & Capabilities |
|---|---|
| [`hexaqueue-core`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/hexaqueue_core) | Domain models, DAG dependency engine, state machines, and port interfaces. |
| [`hexaqueue-cli`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/hexaqueue_cli) | `hq` developer and operator command-line interface. |
| [`hexaqueue-server`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/hexaqueue_server) | Central scheduler, DAG controller daemon, and priority queue coordination. |
| [`hexaqueue-worker`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/hexaqueue_worker) | Compute node execution daemon (local subprocess, rootless Podman/Apptainer). |
| [`hexaqueue-collateral`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/hexaqueue_collateral) | Direct-to-storage presigned ingestion and staging storage service. |
| [`hexaqueue-scanner`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/hexaqueue_scanner) | ClamAV, YARA malware, and security policy inspection daemon. |
| [`hexaqueue-monitor`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/hexaqueue_monitor) | Heartbeat telemetry, resource metrics, and budget accounting daemon. |
| [`hexaqueue-dashboard`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/hexaqueue_dashboard) | Web portal, operator console, and run inspection UI. |
| [`hexaqueue-github-runner`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/hexaqueue_github_runner) | GitHub Actions JIT ephemeral runner autoscaler and webhook bridge ([Guide](guides/github-actions-runner.md)). |
| [`hexaqueue-gitlab-runner`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/hexaqueue_gitlab_runner) | GitLab CI/CD custom runner executor daemon. |
| [`hexaqueue-kueue`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/hexaqueue_kueue) | Kubernetes Batch v1 and Kueue cloud-native scheduler bridge. |
| [`hexaqueue-workflow`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/hexaqueue_workflow) | Distributed cluster engine and artifact staging adapter for Hexaflow. |
| [`pytest-hexaqueue`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/pytest_hexaqueue) | Distributed Pytest execution, test suite slicing engine, and multi-CSP free-tier runner plugin ([Guide](guides/pytest-distributed-execution.md)). |
| [`hexaqueue`](https://github.com/TheTrueSCU/hexaqueue/tree/main/packages/hexaqueue) | Umbrella convenience metapackage (`pip install hexaqueue` installs all workspace subpackages; optional extras: `dotenv`, `gcp`, `github`, `oci`, `oracle`, `pytest`, `sentry`). |
