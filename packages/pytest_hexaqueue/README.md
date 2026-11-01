# 🧪 `pytest-hexaqueue`

> Distributed Test Execution, Slicing Engine, and Multi-CSP Free-Tier Bursting Plugin for Pytest.

[![PyPI: pytest-hexaqueue](https://img.shields.io/pypi/v/pytest-hexaqueue.svg)](https://pypi.org/project/pytest-hexaqueue/)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Part of Hexaqueue](https://img.shields.io/badge/part%20of-hexaqueue-blue.svg)](https://dopplereffect.us/hexaqueue/)
[![Built with Hexastack](https://img.shields.io/badge/built%20with-hexastack-blueviolet.svg)](https://dopplereffect.us/hexastack/)
[![Governed by Hexaqual](https://img.shields.io/badge/governed%20by-hexaqual-10b981.svg)](https://dopplereffect.us/hexaqual/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

---

## 🎯 Overview

`pytest-hexaqueue` is a drop-in distributed execution plugin for pytest that slices test suites and fans out execution across Hexaqueue worker clusters and the federated **Multi-CSP Free-Tier Mesh** (OCI, GCP, AWS, Azure, Local).

### Distributed Slicing Architecture

```mermaid
sequenceDiagram
    autonumber
    participant CLI as Developer Terminal (pytest)
    participant Plugin as pytest-hexaqueue
    participant CAS as hexaqueue-collateral (CAS Storage)
    participant Server as hexaqueue-server (Controller)
    participant Mesh as Multi-CSP Workers (OCI, GCP, Local)

    CLI->>Plugin: Collect test suite (session.items)
    Plugin->>Plugin: Partition into N balanced execution slices
    Plugin->>CAS: Snapshot workspace delta into CAS bundle (SHA-256)
    Plugin->>Server: SubmitRunCommand(jobs=[slice_1, ..., slice_N])
    Server->>Mesh: Dispatch test slices in parallel
    Mesh-->>Plugin: Stream test outcome events over gRPC/HTTP
    Plugin->>CLI: Live terminal progress & assertion reporting
    Plugin->>Plugin: Aggregate remote .coverage and JUnit XML locally
```

---

## 🚀 Quickstart & Usage

### 1. Installation

```bash
uv add --dev pytest-hexaqueue
# or
pip install pytest-hexaqueue
```

### 2. Running Distributed Tests

```bash
# Fan out tests across 4 cluster slices
pytest --hexaqueue --hq-slices 4

# Run strictly against the zero-cost Free-Tier mesh
pytest --hexaqueue --hq-slices 5 --hq-free-tier

# Specify explicit controller endpoint
pytest --hexaqueue --hq-server http://hexaqueue.internal:8000 --hq-pool ci-fast
```

---

## ⚙️ CLI Options

| Option | Environment Variable | Default | Description |
|---|---|---|---|
| `--hexaqueue` | `HEXAQUEUE_PYTEST` | `False` | Enable Hexaqueue distributed test execution |
| `--hq-server` | `HEXAQUEUE_SERVER_URL` | `http://127.0.0.1:8000` | Hexaqueue server API endpoint |
| `--hq-slices` | `HEXAQUEUE_SLICES` | `4` | Number of parallel execution slices |
| `--hq-pool` | `HEXAQUEUE_POOL` | `default` | Target compute instance pool |
| `--hq-free-tier` | `HEXAQUEUE_FREE_TIER` | `False` | Enforce zero-cost multi-CSP free-tier bursting |
| `--hq-fallback` | `HEXAQUEUE_LOCAL_FALLBACK` | `True` | Fall back to local execution if cluster is unreachable |
