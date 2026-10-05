# Packages Catalog

> Hexaqueue is organized as a modular monorepo of specialized packages that can be installed individually or consumed as a unified orchestrator via `hexaqueue[all]`.

---

| Package | Purpose & Capabilities |
|---|---|
| [`hexaqueue-core`](packages/hexaqueue_core/) | Domain models, DAG dependency engine, state machines, and port interfaces. |
| [`hexaqueue-cli`](packages/hexaqueue_cli/) | `hq` developer and operator command-line interface. |
| [`hexaqueue-server`](packages/hexaqueue_server/) | Central scheduler, DAG controller daemon, and priority queue coordination. |
| [`hexaqueue-worker`](packages/hexaqueue_worker/) | Compute node execution daemon (local subprocess, rootless Podman/Apptainer). |
| [`hexaqueue-collateral`](packages/hexaqueue_collateral/) | Direct-to-storage presigned ingestion and staging storage service. |
| [`hexaqueue-scanner`](packages/hexaqueue_scanner/) | ClamAV, YARA malware, and security policy inspection daemon. |
| [`hexaqueue-monitor`](packages/hexaqueue_monitor/) | Heartbeat telemetry, resource metrics, and budget accounting daemon. |
| [`hexaqueue-dashboard`](packages/hexaqueue_dashboard/) | Web portal, operator console, and run inspection UI. |
| [`hexaqueue-github-runner`](packages/hexaqueue_github_runner/) | GitHub Actions JIT ephemeral runner autoscaler and webhook bridge. |
| [`hexaqueue-gitlab-runner`](packages/hexaqueue_gitlab_runner/) | GitLab CI/CD custom runner executor daemon. |
| [`hexaqueue-kueue`](packages/hexaqueue_kueue/) | Kubernetes Batch v1 and Kueue cloud-native scheduler bridge. |
| [`hexaqueue-workflow`](packages/hexaqueue_workflow/) | Temporal activity worker and Argo workflow DAG driver. |
| [`hexaqueue`](packages/hexaqueue/) | Umbrella convenience metapackage (`hexaqueue[all]`). |
