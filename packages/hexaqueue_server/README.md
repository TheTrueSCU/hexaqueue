# 🏛️ `hexaqueue-server`

> High-Availability Central Controller and Batch Scheduling Daemon.

[![PyPI: hexaqueue-server](https://img.shields.io/pypi/v/hexaqueue-server.svg)](https://pypi.org/project/hexaqueue-server/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_server)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![Part of Hexaqueue](https://img.shields.io/badge/part%20of-hexaqueue-blue.svg)](https://dopplereffect.us/hexaqueue/)
[![Built with Hexastack](https://img.shields.io/badge/built%20with-hexastack-blueviolet.svg)](https://dopplereffect.us/hexastack/)
[![Governed by Hexaqual](https://img.shields.io/badge/governed%20by-hexaqual-10b981.svg)](https://dopplereffect.us/hexaqual/)
[![Tested on Hexaqueue](https://img.shields.io/badge/tested%20on-hexaqueue-blue.svg)](https://dopplereffect.us/hexaqueue/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

> Part of the [**Hexaqueue Scheduler**](https://dopplereffect.us/hexaqueue/) · Built on [**Hexastack**](https://dopplereffect.us/hexastack/) · Governed by [**Hexaqual**](https://dopplereffect.us/hexaqual/).

---

## 🏗️ Architecture & Dependencies

```mermaid
graph TD
    subgraph S1["hexaqueue-server"]
        SCHED["Scheduling Engine (Priority Aging, Fair-Share, Backfill, Preemption)"]
        LEASE["SliceLeaseCoordinator (Pull-Based Worker Lease Dispatch)"]
        AUTOSCALE["BudgetAwareInstancePoolAutoscaler (Elastic Scale-to-Zero)"]
        HA["HA Leader Election (Redis / Postgres Lease)"]
        GRPC_API["gRPC Control Plane Service"]
        REST_API["FastAPI REST & Worker Pool Management Endpoints"]
    end

    subgraph S2["Internal & Hexastack Dependencies"]
        HQ_CORE["hexaqueue-core (Domain Models & Storage Ports)"]
        HQ_COLLATERAL["hexaqueue-collateral"]
        HQ_MONITOR["hexaqueue-monitor"]
        HS_AUTH["hexastack-auth (SPIFFE/mTLS & OIDC)"]
        HS_CORE["hexastack-core (ContainerPort Composition Root)"]
        HS_CQRS["hexastack-cqrs"]
        HS_DB["hexastack-db (PostgreSQL / SQLite)"]
        HS_EVENTS["hexastack-events (NATS JetStream & Redis)"]
        HS_FASTAPI["hexastack-fastapi"]
        HS_GRPC["hexastack-grpc"]
        HS_LOG["hexastack-logging"]
        HS_MCP["hexastack-mcp"]
        HS_OTEL["hexastack-otel"]
    end

    S1 --> HQ_CORE
    S1 --> HQ_COLLATERAL
    S1 --> HQ_MONITOR
    S1 --> HS_AUTH
    S1 --> HS_CORE
    S1 --> HS_CQRS
    S1 --> HS_DB
    S1 --> HS_EVENTS
    S1 --> HS_FASTAPI
    S1 --> HS_GRPC
    S1 --> HS_LOG
    S1 --> HS_MCP
    S1 --> HS_OTEL
```

---

## ⚙️ Configuration & Elastic Cloud Autoscaling

`hexaqueue-server` operates as a standalone daemon or within containerized control planes.

```bash
# Start server with default HTTP (8000) and worker pool (8001) ports
hq server start --host 0.0.0.0 --port 8000
```

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `HEXAQUEUE_CSP_PROVIDER` | Cloud service provider enum (`AWS`, `AZURE`, `GCP`, `LOCAL`, `OCI`, `ONPREM`; see cloud adapters for active backend support) | `LOCAL` |
| `HEXAQUEUE_WORKER_PORT` | Optional dedicated port for worker agent registration and lease polling (e.g. set `8001` to enable) | `None` |
| `HEXAQUEUE_OCI_INSTANCE_POOL_ID` | OCI Instance Pool OCID for dynamic scale-to-zero compute pools | `None` |
| `HEXAQUEUE_COLLATERAL_BUCKET` | OCI Object Storage bucket name for content-addressed collateral | `hexaqueue-collateral` |
| `HEXAQUEUE_ADMIN_TOKEN` | Bearer token for privileged control plane actions | `None` |
