# ⏳ `hexaqueue-workflow`

> Distributed Cluster Engine & Artifact Staging for Hexaflow.

[![PyPI: hexaqueue-workflow](https://img.shields.io/pypi/v/hexaqueue-workflow.svg)](https://pypi.org/project/hexaqueue-workflow/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_workflow)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

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
