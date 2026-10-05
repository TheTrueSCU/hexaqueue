# Hexaqueue

> **Cloud-Agnostic HPC Batch Scheduler and Distributed Job Orchestrator for Python 3.13+.**

[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Architecture](https://img.shields.io/badge/architecture-hexagonal-emerald.svg)](architecture.md)
[![Built with Hexastack](https://img.shields.io/badge/built%20with-hexastack-blueviolet.svg)](https://github.com/TheTrueSCU/hexastack)

---

## 🌟 Why Hexaqueue?

Modern HPC batch scheduling and distributed ML pipeline orchestration require high performance, zero cross-job contamination, multi-cloud flexibility, and a seamless developer loop. Built on [**Hexastack**](https://github.com/TheTrueSCU/hexastack) (Hexagonal Architecture & CQRS for Python), **Hexaqueue** solves this by establishing strict hexagonal architectural boundaries, native cloud-deference, and a $0 cloud spend developer experience:

```mermaid
graph TD
    subgraph DrivingAdapters ["Driving Adapters (Inbound / Control)"]
        CLI["hexaqueue-cli (hq Typer CLI)"]
        DASH["hexaqueue-dashboard (Web UI)"]
        GH["hexaqueue-github-runner (GitHub Actions JIT)"]
        GL["hexaqueue-gitlab-runner (GitLab CI/CD)"]
    end

    subgraph Hexagon ["Hexagonal Core"]
        SCHED["JobQueuePort & SchedulerControllerPort"]
        DAG["JobDagEngine & State Machine Rollup"]
        STORAGE_PORT["StorageVolumePort & CollateralPort"]
        RUNTIME_PORT["ExecutionRuntimePort"]
    end

    subgraph DrivenAdapters ["Driven Adapters (Outbound / Compute & Infrastructure)"]
        WORKER["hexaqueue-worker (Local Subprocess & Containers)"]
        COLLATERAL["hexaqueue-collateral (Presigned S3/GCS/Blob Staging)"]
        SCANNER["hexaqueue-scanner (ClamAV & YARA Security Scan)"]
        MONITOR["hexaqueue-monitor (Heartbeat & Resource Metrics)"]
        KUEUE["hexaqueue-kueue (Kubernetes Kueue & Batch v1)"]
        WF["hexaqueue-workflow (Temporal & Argo DAG Driver)"]
    end

    CLI --> SCHED
    DASH --> SCHED
    GH --> SCHED
    GL --> SCHED

    SCHED --> DAG
    DAG --> STORAGE_PORT
    DAG --> RUNTIME_PORT

    RUNTIME_PORT --> WORKER
    RUNTIME_PORT --> KUEUE
    RUNTIME_PORT --> WF
    STORAGE_PORT --> COLLATERAL
    STORAGE_PORT --> SCANNER
    SCHED --> MONITOR
```

---

## 🚀 Quickstart: Local Developer Loop

Execute multi-stage DAG compute pipelines locally with zero cloud configuration:

```bash
# 1. Submit and watch a pipeline
uv run hq run submit examples/data-pipeline/pipelines/etl_workflow.yaml --watch

# 2. Check execution status
uv run hq status demo-etl-run

# 3. Inspect task execution logs
uv run hq logs stage1-extract
```
