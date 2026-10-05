# 🐝 `hexaqueue-worker`

> Lightweight compute node execution daemon with GPU isolation and real-time streaming.

[![PyPI: hexaqueue-worker](https://img.shields.io/pypi/v/hexaqueue-worker.svg)](https://pypi.org/project/hexaqueue-worker/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_worker)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![Part of Hexaqueue](https://img.shields.io/badge/part%20of-hexaqueue-blue.svg)](https://dopplereffect.us/hexaqueue/)
[![Built with Hexastack](https://img.shields.io/badge/built%20with-hexastack-blueviolet.svg)](https://dopplereffect.us/hexastack/)
[![Governed by Hexaqual](https://img.shields.io/badge/governed%20by-hexaqual-10b981.svg)](https://dopplereffect.us/hexaqual/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

> Part of the [**Hexaqueue Scheduler**](https://dopplereffect.us/hexaqueue/) · Built on [**Hexastack**](https://dopplereffect.us/hexastack/) · Governed by [**Hexaqual**](https://dopplereffect.us/hexaqual/).

---

## 🏗️ Architecture & Dependencies

```mermaid
graph TD
    subgraph S1["hexaqueue-worker"]
        RUNNER["Execution Runtimes (cgroups v2, Docker/Podman, Apptainer)"]
        GPU["GPU Masking (NVML & CUDA_VISIBLE_DEVICES)"]
        STREAM["Log & Telemetry gRPC Streaming"]
    end

    subgraph S2["Internal & Hexastack Dependencies"]
        HQ_CORE["hexaqueue-core"]
        HS_AUTH["hexastack-auth (SPIFFE mTLS)"]
        HS_CORE["hexastack-core"]
        HS_GRPC["hexastack-grpc (Bidirectional Streams)"]
        HS_LOG["hexastack-logging (structlog)"]
    end

    S1 --> HQ_CORE
    S1 --> HS_AUTH
    S1 --> HS_CORE
    S1 --> HS_GRPC
    S1 --> HS_LOG
```
