# 🏛️ `hexaqueue-server`

> High-Availability Central Controller and Batch Scheduling Daemon.

[![PyPI: hexaqueue-server](https://img.shields.io/pypi/v/hexaqueue-server.svg)](https://pypi.org/project/hexaqueue-server/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_server)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![Part of Hexaqueue](https://img.shields.io/badge/part%20of-hexaqueue-blue.svg)](https://dopplereffect.us/hexaqueue/)
[![Built with Hexastack](https://img.shields.io/badge/built%20with-hexastack-blueviolet.svg)](https://dopplereffect.us/hexastack/)
[![Governed by Hexaqual](https://img.shields.io/badge/governed%20by-hexaqual-10b981.svg)](https://dopplereffect.us/hexaqual/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

> Part of the [**Hexaqueue Scheduler**](https://dopplereffect.us/hexaqueue/) · Built on [**Hexastack**](https://dopplereffect.us/hexastack/) · Governed by [**Hexaqual**](https://dopplereffect.us/hexaqual/).

---

## 🏗️ Architecture & Dependencies

```mermaid
graph TD
    subgraph S1["hexaqueue-server"]
        SCHED["Scheduling Engine (Priority Aging, Fair-Share, Backfill, Preemption)"]
        HA["HA Leader Election (Redis / Postgres Lease)"]
        GRPC_API["gRPC Control Plane Service"]
        REST_API["FastAPI REST Management Endpoints"]
    end

    subgraph S2["Internal & Hexastack Dependencies"]
        HQ_CORE["hexaqueue-core"]
        HS_AUTH["hexastack-auth (SPIFFE/mTLS & OIDC)"]
        HS_CORE["hexastack-core"]
        HS_CQRS["hexastack-cqrs"]
        HS_DB["hexastack-db (PostgreSQL / SQLite)"]
        HS_EVENTS["hexastack-events (NATS JetStream & Redis)"]
        HS_FASTAPI["hexastack-fastapi"]
        HS_GRPC["hexastack-grpc"]
        HS_OTEL["hexastack-otel"]
    end

    S1 --> HQ_CORE
    S1 --> HS_AUTH
    S1 --> HS_CORE
    S1 --> HS_CQRS
    S1 --> HS_DB
    S1 --> HS_EVENTS
    S1 --> HS_FASTAPI
    S1 --> HS_GRPC
    S1 --> HS_OTEL
```
