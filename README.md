# ⚡ Hexaqueue

> **Cloud-Agnostic HPC Batch Scheduler and Distributed Job Orchestrator**

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/TheTrueSCU/hexaqueue)
[![CI](https://github.com/TheTrueSCU/hexaqueue/actions/workflows/ci.yml/badge.svg)](https://github.com/TheTrueSCU/hexaqueue/actions/workflows/ci.yml)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![PyPI: hexaqueue](https://img.shields.io/pypi/v/hexaqueue.svg)](https://pypi.org/project/hexaqueue/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

[![Built with Hexastack](https://img.shields.io/badge/built%20with-hexastack-blueviolet.svg)](https://dopplereffect.us/hexastack/)
[![Powered by Hexaflow](https://img.shields.io/badge/powered%20by-hexaflow-0284c7.svg)](https://dopplereffect.us/hexaflow/)
[![Governed by Hexaqual](https://img.shields.io/badge/governed%20by-hexaqual-10b981.svg)](https://dopplereffect.us/hexaqual/)
[![Tested on Hexaqueue](https://img.shields.io/badge/tested%20on-hexaqueue-blue.svg)](https://dopplereffect.us/hexaqueue/)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type checker: ty](https://img.shields.io/badge/type%20checker-ty-blueviolet.svg)](https://github.com/astral-sh/ty)
[![Accessibility: WCAG 2.1 AA](https://img.shields.io/badge/accessibility-WCAG%202.1%20AA-15803d.svg)](tests/e2e/test_dashboard_accessibility.py)

[![OpenSSF Scorecard](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.scorecard.dev%2Fprojects%2Fgithub.com%2FTheTrueSCU%2Fhexaqueue&query=%24.score&label=OpenSSF%20Scorecard&color=blue)](https://securityscorecards.dev/viewer/?uri=github.com/TheTrueSCU/hexaqueue)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/14535/badge)](https://www.bestpractices.dev/projects/14535)
[![OpenSSF Best Practices: Progress](https://img.shields.io/cii/percentage/14535?label=OpenSSF%20Best%20Practices%3A%20Progress)](https://www.bestpractices.dev/projects/14535)

> 🏛️ **Built 100% on [Hexastack](https://dopplereffect.us/hexastack/)** · 🌊 **Workflows powered by [Hexaflow](https://dopplereffect.us/hexaflow/)** · 🛡️ **Governed by [Hexaqual](https://dopplereffect.us/hexaqual/)**


---

## 🧭 Monorepo Package Architecture

```mermaid
graph TD
    subgraph S1["User & Operator Interfaces"]
        CLI["hexaqueue-cli (hq CLI)"]
        DASH["hexaqueue-dashboard (Web UI & Console)"]
    end

    subgraph S2["Control Plane & Daemons"]
        SERVER["hexaqueue-server (HA Controller, Lease Coordinator & Autoscaler)"]
        MONITOR["hexaqueue-monitor (Telemetry & Budget Daemon)"]
        COLLATERAL["hexaqueue-collateral (Direct Presigned Upload & Staging)"]
        SCANNER["hexaqueue-scanner (Malware & AV Verification Daemon)"]
    end

    subgraph S3["Compute Execution Plane"]
        WORKER["hexaqueue-worker (Pull-Based Worker Agent & Compute Daemon)"]
    end

    subgraph S4["Ecosystem CI & Workflow Hooks"]
        GH["hexaqueue-github-runner (GitHub Actions JIT Autoscaler)"]
        GL["hexaqueue-gitlab-runner (GitLab Custom Executor)"]
        KUEUE["hexaqueue-kueue (Kubernetes Batch v1 Bridge)"]
        WORKFLOW["hexaqueue-workflow (Distributed Hexaflow Engine & Artifact Staging)"]
        PYTEST["pytest-hexaqueue (Distributed Slicing & Free-Tier Plugin)"]
    end

    subgraph S5["Foundation Core"]
        CORE["hexaqueue-core (Domain Models, Ports & State Machines)"]
    end

    CLI --> CORE
    DASH --> CORE
    SERVER --> CORE
    MONITOR --> CORE
    COLLATERAL --> CORE
    SCANNER --> CORE
    WORKER --> CORE
    GH --> CORE
    GL --> CORE
    KUEUE --> CORE
    WORKFLOW --> CORE
    PYTEST --> CORE

    CLI -.->|gRPC / REST| SERVER
    DASH -.->|gRPC / REST| SERVER
    WORKER <==>|Bidirectional gRPC Stream| SERVER
    COLLATERAL -.->|Events| SCANNER
    SCANNER -.->|Events| SERVER
    MONITOR -.->|Telemetry & Budget Holds| SERVER
```

---

## 📦 Hexastack Dependency Map

```mermaid
graph TD
    subgraph S1["Hexaqueue Packages"]
        HQ_CORE["hexaqueue-core"]
        HQ_CLI["hexaqueue-cli"]
        HQ_SERVER["hexaqueue-server"]
        HQ_WORKER["hexaqueue-worker"]
        HQ_COLLATERAL["hexaqueue-collateral"]
        HQ_SCANNER["hexaqueue-scanner"]
        HQ_MONITOR["hexaqueue-monitor"]
        HQ_DASHBOARD["hexaqueue-dashboard"]
        HQ_WORKFLOW["hexaqueue-workflow"]
    end

    subgraph S2["Hexastack Foundation"]
        HS_AUTH["hexastack-auth (SPIFFE/mTLS & OIDC)"]
        HS_CLI["hexastack-cli (Typer & Rich Output)"]
        HS_CORE["hexastack-core (DI Container & Ports)"]
        HS_CQRS["hexastack-cqrs (Commands, Queries, Events)"]
        HS_DB["hexastack-db (PostgreSQL / SQLite Persistence)"]
        HS_EVENTS["hexastack-events (NATS JetStream & Redis)"]
        HS_FASTAPI["hexastack-fastapi (REST & Middleware)"]
        HS_GRPC["hexastack-grpc (Protobuf Streaming & Reflection)"]
        HS_LOG["hexastack-logging (Structured JSON Logs)"]
        HS_MCP["hexastack-mcp (Model Context Protocol)"]
        HS_OTEL["hexastack-otel (OpenTelemetry & Prometheus)"]
        HS_UI["hexastack-ui (NiceGUI DevTools & Web UI)"]
    end

    HQ_CORE --> HS_CORE
    HQ_CORE --> HS_CQRS

    HQ_CLI --> HS_AUTH
    HQ_CLI --> HS_CLI
    HQ_CLI --> HS_CORE
    HQ_CLI --> HS_CQRS
    HQ_CLI --> HS_GRPC

    HQ_SERVER --> HS_AUTH
    HQ_SERVER --> HS_CORE
    HQ_SERVER --> HS_CQRS
    HQ_SERVER --> HS_DB
    HQ_SERVER --> HS_EVENTS
    HQ_SERVER --> HS_FASTAPI
    HQ_SERVER --> HS_GRPC
    HQ_SERVER --> HS_LOG
    HQ_SERVER --> HS_MCP
    HQ_SERVER --> HS_OTEL

    HQ_WORKER --> HS_AUTH
    HQ_WORKER --> HS_CORE
    HQ_WORKER --> HS_GRPC
    HQ_WORKER --> HS_LOG

    HQ_COLLATERAL --> HS_AUTH
    HQ_COLLATERAL --> HS_CORE
    HQ_COLLATERAL --> HS_EVENTS
    HQ_COLLATERAL --> HS_FASTAPI

    HQ_SCANNER --> HS_AUTH
    HQ_SCANNER --> HS_CORE
    HQ_SCANNER --> HS_EVENTS
    HQ_SCANNER --> HS_LOG

    HQ_MONITOR --> HS_CORE
    HQ_MONITOR --> HS_EVENTS
    HQ_MONITOR --> HS_OTEL

    HQ_DASHBOARD --> HS_AUTH
    HQ_DASHBOARD --> HS_CORE
    HQ_DASHBOARD --> HS_CQRS
    HQ_DASHBOARD --> HS_FASTAPI
    HQ_DASHBOARD --> HS_GRPC
    HQ_DASHBOARD --> HS_UI

    HQ_WORKFLOW --> HS_CORE
    HQ_WORKFLOW --> HS_GRPC
```

---

## ⚡ GitHub Action (`TheTrueSCU/hexaqueue`)

Use the repository's composite action (`action.yml`) in CI workflows to install `hq`, probe the fleet, and establish the zero-trust OpenSSH tunnel for `pytest-hexaqueue`:

```yaml
- uses: TheTrueSCU/hexaqueue@1e7b3c4625c82bece17dbc9eafc72664e4bd501c # v0.12.1
  with:
    cluster-env: ${{ secrets.HEXAQUEUE_ENV }}
    probe-only: "false"
    auto-tunnel: "true"
    step-summary: "true"
```

---

## 📚 Package Directory Index

| Package | Description |
|---|---|
| [`hexaqueue`](packages/hexaqueue/README.md) | Umbrella metapackage (`pip install hexaqueue`, optional `[oci]`, `[github]`, `[gcp]`, `[oracle]`, `[dotenv]`, `[pytest]`, `[sentry]`) |
| [`hexaqueue-core`](packages/hexaqueue_core/README.md) | Pure domain models, lifecycle state machines, port interfaces |
| [`hexaqueue-cli`](packages/hexaqueue_cli/README.md) | `hq` interactive terminal CLI |
| [`hexaqueue-server`](packages/hexaqueue_server/README.md) | HA controller, lease coordinator & scale-to-zero autoscaler engine |
| [`hexaqueue-worker`](packages/hexaqueue_worker/README.md) | Compute daemon & autonomous pull-based worker agent (cgroups v2, GPU isolation) |
| [`hexaqueue-collateral`](packages/hexaqueue_collateral/README.md) | Direct presigned multi-part upload & OCI Object Storage staging service |
| [`hexaqueue-scanner`](packages/hexaqueue_scanner/README.md) | Malware scanning, AV (ClamAV/YARA) & quarantine daemon |
| [`hexaqueue-monitor`](packages/hexaqueue_monitor/README.md) | Health, heartbeat telemetry & budget tracking daemon |
| [`hexaqueue-dashboard`](packages/hexaqueue_dashboard/README.md) | Web interface, cluster visualizer & operator console |
| [`hexaqueue-github-runner`](packages/hexaqueue_github_runner/README.md) | GitHub Actions JIT autoscaler & webhook bridge |
| [`hexaqueue-gitlab-runner`](packages/hexaqueue_gitlab_runner/README.md) | GitLab CI/CD Custom Executor driver |
| [`hexaqueue-kueue`](packages/hexaqueue_kueue/README.md) | Kubernetes Batch v1 & Kueue controller bridge |
| [`hexaqueue-workflow`](packages/hexaqueue_workflow/README.md) | Distributed Hexaflow cluster workflow engine & artifact staging adapter |
| [`pytest-hexaqueue`](packages/pytest_hexaqueue/README.md) | Distributed Pytest execution, test suite slicing engine, and multi-CSP free-tier runner plugin |
