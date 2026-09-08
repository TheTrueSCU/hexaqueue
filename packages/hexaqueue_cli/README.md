# 💻 `hexaqueue-cli`

> Modern interactive developer and operator terminal CLI (`hq`).

[![PyPI: hexaqueue-cli](https://img.shields.io/pypi/v/hexaqueue-cli.svg)](https://pypi.org/project/hexaqueue-cli/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_cli)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

---

## 🏗️ Architecture & Dependencies

```mermaid
graph TD
    subgraph S1["hexaqueue-cli (hq)"]
        COMMANDS["CLI Commands (submit, stat, top, why, explain, logs, fairshare)"]
    end

    subgraph S2["Internal & Hexastack Dependencies"]
        HQ_CORE["hexaqueue-core"]
        HS_CLI["hexastack-cli (Typer, Rich & pipe auto-detection)"]
        HS_CORE["hexastack-core"]
        HS_CQRS["hexastack-cqrs"]
        HS_GRPC["hexastack-grpc (gRPC client transport)"]
    end

    COMMANDS --> HQ_CORE
    COMMANDS --> HS_CLI
    COMMANDS --> HS_CORE
    COMMANDS --> HS_CQRS
    COMMANDS --> HS_GRPC
```
