# 💻 `hexaqueue-cli`

> Modern interactive developer and operator terminal CLI (`hq`).

[![PyPI: hexaqueue-cli](https://img.shields.io/pypi/v/hexaqueue-cli.svg)](https://pypi.org/project/hexaqueue-cli/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_cli)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![Part of Hexaqueue](https://img.shields.io/badge/part%20of-hexaqueue-blue.svg)](https://dopplereffect.us/hexaqueue/)
[![Built with Hexastack](https://img.shields.io/badge/built%20with-hexastack-blueviolet.svg)](https://dopplereffect.us/hexastack/)
[![Governed by Hexaqual](https://img.shields.io/badge/governed%20by-hexaqual-10b981.svg)](https://dopplereffect.us/hexaqual/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

> Part of the [**Hexaqueue Scheduler**](https://dopplereffect.us/hexaqueue/) · Built on [**Hexastack**](https://dopplereffect.us/hexastack/) · Governed by [**Hexaqual**](https://dopplereffect.us/hexaqual/).

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
