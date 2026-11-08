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
        AGENT["WorkerAgent (Autonomous Pull-Based Lease Poller & Runner)"]
        RUNNER["Execution Runtimes (cgroups v2, Docker/Podman, Apptainer)"]
        GPU["GPU Masking (NVML & CUDA_VISIBLE_DEVICES)"]
        STREAM["Log & Telemetry gRPC Streaming"]
    end

    subgraph S2["Internal & Hexastack Dependencies"]
        HQ_CORE["hexaqueue-core (Lease Models & Storage Ports)"]
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

---

## 🏃 Autonomous Pull-Based Worker Agent

In elastic cloud environments (e.g. OCI scale-to-zero instance pools under private subnets), worker nodes run the autonomous `WorkerAgent`:

```bash
# Start autonomous worker agent connecting to controller
hq-worker-agent --controller-url http://10.0.1.101:8001
```

### Agent Lifecycle
1. **Dynamic Registration**: On boot, registers hardware footprint (vCPUs, RAM, architecture) with the controller at `POST /worker/register`.
2. **Lease Polling**: Actively requests work slices via `POST /worker/{id}/lease`.
3. **Collateral Ingestion**: Fetches and unpacks content-addressed workspace bundles (via local cache or signed OCI Object Storage PAR URLs).
4. **Isolated Virtualenv Execution**: Spawns test runners with isolated environments (`VIRTUAL_ENV`, `PATH`).
5. **Outcome Reporting**: Posts exit codes, JUnit reports, and coverage back via `POST /worker/{id}/report`.
6. **Heartbeat & Self-Healing**: Transmits heartbeats every 10 seconds; backs off gracefully when the queue is drained so the cloud pool can scale down.
