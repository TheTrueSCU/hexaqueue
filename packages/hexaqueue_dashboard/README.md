# 🖥️ `hexaqueue-dashboard`

> Modern web portal, cluster heatmap visualizer, live terminal log viewer, and operator console.

[![PyPI: hexaqueue-dashboard](https://img.shields.io/pypi/v/hexaqueue-dashboard.svg)](https://pypi.org/project/hexaqueue-dashboard/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_dashboard)](https://codecov.io/github/TheTrueSCU/hexaqueue)
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
    subgraph S1["hexaqueue-dashboard"]
        UI["NiceGUI / FastAPI Web SPA"]
        HEATMAP["Cluster Node & GPU Heatmap Grid"]
        TERM["Live Browser ANSI Log Viewer"]
        AUDIT["Quarantine & Security Audit Console"]
    end

    subgraph S2["Internal & Hexastack Dependencies"]
        HQ_COLLATERAL["hexaqueue-collateral"]
        HQ_CORE["hexaqueue-core"]
        HQ_SERVER["hexaqueue-server"]
        HQ_WORKER["hexaqueue-worker"]
        HS_AUTH["hexastack-auth (OIDC SSO & RBAC)"]
        HS_CORE["hexastack-core"]
        HS_CQRS["hexastack-cqrs"]
        HS_FASTAPI["hexastack-fastapi"]
        HS_GRPC["hexastack-grpc (Real-Time Server Channels)"]
        HS_UI["hexastack-ui[nicegui] (DevTools & Web UI Components)"]
    end

    S1 --> HQ_COLLATERAL
    S1 --> HQ_CORE
    S1 --> HQ_SERVER
    S1 --> HQ_WORKER
    S1 --> HS_AUTH
    S1 --> HS_CORE
    S1 --> HS_CQRS
    S1 --> HS_FASTAPI
    S1 --> HS_GRPC
    S1 --> HS_UI
```
