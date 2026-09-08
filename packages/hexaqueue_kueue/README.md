# ☸️ `hexaqueue-kueue`

> Kubernetes Batch v1 & Kueue Scheduler Controller Bridge.

[![PyPI: hexaqueue-kueue](https://img.shields.io/pypi/v/hexaqueue-kueue.svg)](https://pypi.org/project/hexaqueue-kueue/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_kueue)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

---

## 🏗️ Architecture & Dependencies

```mermaid
graph TD
    subgraph S1["hexaqueue-kueue"]
        CONTROLLER["Kubernetes Batch/v1 & Kueue Workload Controller"]
    end

    subgraph S2["Internal Dependencies"]
        HQ_CORE["hexaqueue-core"]
    end

    S1 --> HQ_CORE
```
