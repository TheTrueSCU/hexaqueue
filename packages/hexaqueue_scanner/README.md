# 🛡️ `hexaqueue-scanner`

> Security worker daemon executing hash verification, ClamAV/YARA scans, and artifact quarantine.

[![PyPI: hexaqueue-scanner](https://img.shields.io/pypi/v/hexaqueue-scanner.svg)](https://pypi.org/project/hexaqueue-scanner/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_scanner)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

---

## 🏗️ Architecture & Dependencies

```mermaid
graph TD
    subgraph S1["hexaqueue-scanner"]
        HASH["Stream Checksum Verification (actual == expected)"]
        AV["Malware Scanning (ClamAV / YARA)"]
        PROMOTION["Quarantine Promotion to Clean Active Storage"]
    end

    subgraph S2["Internal & Hexastack Dependencies"]
        HQ_CORE["hexaqueue-core"]
        HS_AUTH["hexastack-auth (SPIFFE mTLS)"]
        HS_CORE["hexastack-core"]
        HS_EVENTS["hexastack-events (Subscribes to Scan Tasks)"]
        HS_LOG["hexastack-logging"]
    end

    S1 --> HQ_CORE
    S1 --> HS_AUTH
    S1 --> HS_CORE
    S1 --> HS_EVENTS
    S1 --> HS_LOG
```
