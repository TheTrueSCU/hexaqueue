# ⏳ `hexaqueue-workflow`

> Distributed Cluster Engine & Artifact Staging for Hexaflow.

[![PyPI: hexaqueue-workflow](https://img.shields.io/pypi/v/hexaqueue-workflow.svg)](https://pypi.org/project/hexaqueue-workflow/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_workflow)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![Part of Hexaqueue](https://img.shields.io/badge/part%20of-hexaqueue-blue.svg)](https://dopplereffect.us/hexaqueue/)
[![Built with Hexastack](https://img.shields.io/badge/built%20with-hexastack-blueviolet.svg)](https://dopplereffect.us/hexastack/)
[![Powered by Hexaflow](https://img.shields.io/badge/powered%20by-hexaflow-0284c7.svg)](https://dopplereffect.us/hexaflow/)
[![Governed by Hexaqual](https://img.shields.io/badge/governed%20by-hexaqual-10b981.svg)](https://dopplereffect.us/hexaqual/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

> Part of the [**Hexaqueue Scheduler**](https://dopplereffect.us/hexaqueue/) · Built on [**Hexastack**](https://dopplereffect.us/hexastack/) · Powered by [**Hexaflow**](https://dopplereffect.us/hexaflow/) · Governed by [**Hexaqual**](https://dopplereffect.us/hexaqual/).

---

## 🏗️ Architecture & Dependencies

```mermaid
graph TD
    subgraph S1["hexaqueue-workflow"]
        ENGINE["HexaqueueDistributedEngine (WorkflowEnginePort)"]
        STAGING["StoragePortArtifactStagingAdapter"]
    end

    subgraph S2["Internal Dependencies"]
        HQ_CORE["hexaqueue-core"]
        HQ_SERVER["hexaqueue-server"]
        HQ_WORKER["hexaqueue-worker"]
    end

    subgraph S3["External Core"]
        HEXAFLOW["hexaflow"]
        HEXASTACK["hexastack-core"]
    end

    S1 --> HQ_CORE
    S1 --> HQ_SERVER
    S1 --> HQ_WORKER
    S1 --> HEXAFLOW
    S1 --> HEXASTACK
```
