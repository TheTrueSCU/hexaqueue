# 💻 `hexaqueue-cli`

> Modern interactive developer and operator terminal CLI (`hq`).

[![PyPI: hexaqueue-cli](https://img.shields.io/pypi/v/hexaqueue-cli.svg)](https://pypi.org/project/hexaqueue-cli/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_cli)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![Part of Hexaqueue](https://img.shields.io/badge/part%20of-hexaqueue-blue.svg)](https://dopplereffect.us/hexaqueue/)
[![Built with Hexastack](https://img.shields.io/badge/built%20with-hexastack-blueviolet.svg)](https://dopplereffect.us/hexastack/)
[![Governed by Hexaqual](https://img.shields.io/badge/governed%20by-hexaqual-10b981.svg)](https://dopplereffect.us/hexaqual/)
[![Tested on Hexaqueue](https://img.shields.io/badge/tested%20on-hexaqueue-blue.svg)](https://dopplereffect.us/hexaqueue/)
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
        HQ_SERVER["hexaqueue-server"]
        HQ_WORKER["hexaqueue-worker"]
        HQ_WORKFLOW["hexaqueue-workflow"]
        HS_AUTH["hexastack-auth"]
        HS_CLI["hexastack-cli (Typer, Rich & pipe auto-detection)"]
        HS_CORE["hexastack-core"]
        HS_CQRS["hexastack-cqrs"]
        HS_GRPC["hexastack-grpc (gRPC client transport)"]
    end

    COMMANDS --> HQ_CORE
    COMMANDS --> HQ_SERVER
    COMMANDS --> HQ_WORKER
    COMMANDS --> HQ_WORKFLOW
    COMMANDS --> HS_AUTH
    COMMANDS --> HS_CLI
    COMMANDS --> HS_CORE
    COMMANDS --> HS_CQRS
    COMMANDS --> HS_GRPC
```

---

## 🛠️ Command Groups & Top-Level Commands

| Command / Group | Description |
|---|---|
| `hq submit` / `hq status` / `hq logs` / `hq top` | Quick pipeline submission, run/job status inspection, log tailing, and live monitor |
| `hq jobs` / `hq list` / `hq cancel` / `hq hold` / `hq release` | Job listing and lifecycle state controls |
| `hq why` / `hq explain` / `hq fairshare` / `hq quota` / `hq stat` | Scheduling explainability, pending diagnostics, and tenant quota views |
| `hq exec` / `hq attach` / `hq nodes` | Interactive PTY execution and compute node inspection |
| `hq admin` | Cluster administration operations |
| `hq auth` | Authentication and token/identity utilities |
| `hq cluster` | Cluster `status`, `ping`, `tunnel`, `sync`, `discover`, `journal`, and `pool` management |
| `hq collateral` | Content-addressed workspace collateral upload and cache management |
| `hq dashboard` | Launch and manage the operator web dashboard (`hexaqueue-dashboard`) |
| `hq mcp` | Expose or run the Model Context Protocol (`MCP`) server adapter |
| `hq node` | Worker node `list` and zero-trust `ssh` diagnostics |
| `hq run` | Multi-stage YAML pipeline `submit`, `list`, and `cancel` commands |
| `hq scanner` (alias: `scan`) | Security artifact scanning and quarantine inspection |
| `hq server` | Start and manage the central controller daemon (`hq server start`) |
| `hq suite` | Test suite submission and management |
| `hq workflow` | Hexaflow workflow execution and DAG orchestration subcommands |
