# 📈 `hexaqueue-monitor`

> Cluster health, worker/server heartbeat pulse monitoring, and two-phase budget accounting daemon.

[![PyPI: hexaqueue-monitor](https://img.shields.io/pypi/v/hexaqueue-monitor.svg)](https://pypi.org/project/hexaqueue-monitor/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_monitor)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

---

## 🏗️ Architecture & Dependencies

```mermaid
graph TD
    subgraph S1["hexaqueue-monitor"]
        HEALTH["Worker Heartbeat & Dead-Node Detection"]
        TELEMETRY["Cluster Utilization Aggregator"]
        BUDGET["Two-Phase Pre-Emptive Budget Reservation & Settlement"]
    end

    subgraph S2["Internal & Hexastack Dependencies"]
        HQ_CORE["hexaqueue-core"]
        HS_CORE["hexastack-core"]
        HS_EVENTS["hexastack-events"]
        HS_OTEL["hexastack-otel (Prometheus /metrics)"]
    end

    S1 --> HQ_CORE
    S1 --> HS_CORE
    S1 --> HS_EVENTS
    S1 --> HS_OTEL
```
