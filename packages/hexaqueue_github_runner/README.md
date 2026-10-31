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
- RAM: `64gb`, `ram-32gb`
- GPU: `gpu-h100`, `a100`, `l4`, `t4`, `v100`, `4-gpu-a100`
- Scratch: `100gb-scratch`, `scratch-50gb`
- Walltime: `2h-walltime`, `90m-walltime`
