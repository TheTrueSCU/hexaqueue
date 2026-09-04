# 🖥️ `hexaqueue-dashboard`

> Modern web portal, cluster heatmap visualizer, live terminal log viewer, and operator console.

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
