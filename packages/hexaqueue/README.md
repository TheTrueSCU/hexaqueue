# ⚡ `hexaqueue` (Umbrella Metapackage)

> Unified distribution providing turnkey installation and multi-component orchestration for Hexaqueue.

[![PyPI: hexaqueue](https://img.shields.io/pypi/v/hexaqueue.svg)](https://pypi.org/project/hexaqueue/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![Part of Hexaqueue](https://img.shields.io/badge/part%20of-hexaqueue-blue.svg)](https://dopplereffect.us/hexaqueue/)
[![Built with Hexastack](https://img.shields.io/badge/built%20with-hexastack-blueviolet.svg)](https://dopplereffect.us/hexastack/)
[![Governed by Hexaqual](https://img.shields.io/badge/governed%20by-hexaqual-10b981.svg)](https://dopplereffect.us/hexaqual/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

> Part of the [**Hexaqueue Scheduler**](https://dopplereffect.us/hexaqueue/) · Built on [**Hexastack**](https://dopplereffect.us/hexastack/) · Governed by [**Hexaqual**](https://dopplereffect.us/hexaqual/).

---

## 🏗️ Architecture & Dependencies

```mermaid
graph TD
    subgraph S1["hexaqueue (Umbrella Metapackage)"]
        META["hexaqueue[all]"]
    end

    subgraph S2["Hexaqueue Workspace Packages"]
        HQ_CLI["hexaqueue-cli"]
        HQ_COLLATERAL["hexaqueue-collateral"]
        HQ_CORE["hexaqueue-core"]
        HQ_DASHBOARD["hexaqueue-dashboard"]
        HQ_GITHUB["hexaqueue-github-runner"]
        HQ_GITLAB["hexaqueue-gitlab-runner"]
        HQ_KUEUE["hexaqueue-kueue"]
        HQ_MONITOR["hexaqueue-monitor"]
        HQ_SCANNER["hexaqueue-scanner"]
        HQ_SERVER["hexaqueue-server"]
        HQ_WORKER["hexaqueue-worker"]
        HQ_WORKFLOW["hexaqueue-workflow"]
    end

    META --> HQ_CLI
    META --> HQ_COLLATERAL
    META --> HQ_CORE
    META --> HQ_DASHBOARD
    META --> HQ_GITHUB
    META --> HQ_GITLAB
    META --> HQ_KUEUE
    META --> HQ_MONITOR
    META --> HQ_SCANNER
    META --> HQ_SERVER
    META --> HQ_WORKER
    META --> HQ_WORKFLOW
```
