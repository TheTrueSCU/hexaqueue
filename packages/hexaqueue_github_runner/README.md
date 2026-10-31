# 🐙 `hexaqueue-github-runner`

> GitHub Actions Dynamic Self-Hosted Runner Autoscaler & Webhook Bridge.

[![PyPI: hexaqueue-github-runner](https://img.shields.io/pypi/v/hexaqueue-github-runner.svg)](https://pypi.org/project/hexaqueue-github-runner/)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://codecov.io/github/TheTrueSCU/hexaqueue/graph/badge.svg?component=hexaqueue_github_runner)](https://codecov.io/github/TheTrueSCU/hexaqueue)
[![Part of Hexaqueue](https://img.shields.io/badge/part%20of-hexaqueue-blue.svg)](https://dopplereffect.us/hexaqueue/)
[![Built with Hexastack](https://img.shields.io/badge/built%20with-hexastack-blueviolet.svg)](https://dopplereffect.us/hexastack/)
[![Governed by Hexaqual](https://img.shields.io/badge/governed%20by-hexaqual-10b981.svg)](https://dopplereffect.us/hexaqual/)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](../../LICENSE)

> Part of the [**Hexaqueue Scheduler**](https://dopplereffect.us/hexaqueue/) · Built on [**Hexastack**](https://dopplereffect.us/hexastack/) · Governed by [**Hexaqual**](https://dopplereffect.us/hexaqual/).

---

## 🏗️ Architecture & Dependencies

```mermaid
graph TD
    subgraph S1["hexaqueue-github-runner"]
        WEBHOOK["GitHub Webhook Ingress (workflow_job.queued)"]
        AUTOSCALER["Dynamic GitHub Runner Autoscaler"]
        JIT["GitHub App JIT Runner Token Minting"]
    end

    subgraph S2["Internal Dependencies"]
        HQ_CORE["hexaqueue-core"]
    end

    S1 --> HQ_CORE
```

---

## 🚀 Quickstart & Usage

### 1. Ingress Webhook Router Setup (FastAPI)

```python
from fastapi import FastAPI
from hexaqueue_github_runner import (
    DynamicGitHubRunnerAutoscaler,
    GitHubApiClient,
    GitHubAppCredentials,
    GitHubWebhookAdapter,
    HmacSha256WebhookVerifier,
    create_github_webhook_router,
)

app = FastAPI()

credentials = GitHubAppCredentials(
    app_id="123456",
    installation_id=7890,
    private_key_pem="<PEM_ENCODED_APP_PRIVATE_KEY>",
)
api_client = GitHubApiClient(credentials=credentials)
autoscaler = DynamicGitHubRunnerAutoscaler(api_client=api_client)
verifier = HmacSha256WebhookVerifier()

adapter = GitHubWebhookAdapter(
    verifier=verifier,
    autoscaler=autoscaler,
    secret="your-github-webhook-secret",
)

# Mount webhook route at /webhooks/github
app.include_router(create_github_webhook_router(adapter))
```

### 2. Supported Runner Labels

Hexaqueue translates GitHub Actions `runs-on` labels dynamically:
- `runs-on: [self-hosted, linux, 16-cores, 64gb, gpu-h100, 100gb-scratch, 2h-walltime]`
- CPU: `16-cores`, `cpu-8`, `4-cpu`
- RAM: `64gb`, `ram-32gb`, `512mb-ram`
- GPU: `gpu-h100`, `a100`, `l4`, `t4`, `v100`, `4-gpu-a100`
- Scratch: `100gb-scratch`, `scratch-50gb`
- Walltime: `2h-walltime`, `90m-walltime`
- Cloud Routing & Free-Tier: `oci`, `gcp`, `aws`, `azure`, `local`, `arm64`, `paid`

---

### 3. Multi-CSP Free-Tier Mesh Autoscaling ($0.00 Spend Invariant)

To burst GitHub Actions runner matrices beyond the standard 2 vCPU limit at zero cloud cost, configure the autoscaler with `MultiCspFreeTierGovernor`:

```python
from hexaqueue_core.adapters.freetier.governor import MultiCspFreeTierGovernor
from hexaqueue_github_runner import DynamicGitHubRunnerAutoscaler

governor = MultiCspFreeTierGovernor()
autoscaler = DynamicGitHubRunnerAutoscaler(
    api_client=api_client,
    free_tier_governor=governor,
)
```

The mesh pools Always-Free compute across all participating providers:
- **OCI Always-Free**: 4 Ampere A1 ARM vCPUs / 24 GB RAM (`runs-on: [self-hosted, arm64, 4-cores]`)
- **GCP Always-Free**: 2 x86 vCPUs / 1 GB RAM (`runs-on: [self-hosted, gcp, 2-cores]`)
- **AWS Free Tier**: 1 x86 vCPU / 1 GB RAM (`runs-on: [self-hosted, aws, 1-core]`)
- **Azure Free Tier**: 1 x86 vCPU / 1 GB RAM (`runs-on: [self-hosted, azure, 1-core]`)
- **Local Workstation**: 2 vCPUs / 2 GB RAM (`runs-on: [self-hosted, local, 2-cores]`)

**Key Invariants:**
1. **10 Total Pooled Free vCPUs**: Matrix jobs dynamically fan out across OCI, GCP, AWS, Azure, and Local nodes concurrently at $0.00 spend.
2. **Instant Quota Recycling**: When an ephemeral runner exits, single-job scratch storage is wiped and provider quota is freed immediately.
3. **Step Summary Verification**: Automatically attaches Check Run summaries documenting the assigned CSP provider, resource footprint, and verified $0.00 cost claim.
