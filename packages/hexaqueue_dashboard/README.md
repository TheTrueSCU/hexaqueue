# 🖥️ `hexaqueue-dashboard`

> Modern web portal, cluster heatmap visualizer, live terminal log viewer, and operator console.

[![PyPI: hexaqueue-dashboard](https://img.shields.io/pypi/v/hexaqueue-dashboard.svg)](https://pypi.org/project/hexaqueue-dashboard/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_dashboard)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![Part of Hexaqueue](https://img.shields.io/badge/part%20of-hexaqueue-blue.svg)](https://dopplereffect.us/hexaqueue/)
[![Built with Hexastack](https://img.shields.io/badge/built%20with-hexastack-blueviolet.svg)](https://dopplereffect.us/hexastack/)
[![Governed by Hexaqual](https://img.shields.io/badge/governed%20by-hexaqual-10b981.svg)](https://dopplereffect.us/hexaqual/)
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
        HQ_CORE["hexaqueue-core"]
        HS_AUTH["hexastack-auth (OIDC SSO & RBAC)"]
        HS_FASTAPI["hexastack-fastapi (ui/nicegui)"]
        HS_GRPC["hexastack-grpc (Real-Time Server Channels)"]
    end

    S1 --> HQ_CORE
    S1 --> HS_AUTH
    S1 --> HS_FASTAPI
    S1 --> HS_GRPC
```
