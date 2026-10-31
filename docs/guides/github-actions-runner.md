# GitHub Actions Dynamic Runner Autoscaler Guide

> High-performance, cost-effective self-hosted GitHub Actions runner autoscaler with zero-trust single-job isolation and dynamic hardware claims.

---

## 🎯 Overview

Hexaqueue provides a first-class, cloud-agnostic integration bridge for GitHub Actions via the [`hexaqueue-github-runner`](../packages/hexaqueue_github_runner/README.md) package. It allows Hexaqueue clusters to serve as an intelligent runner autoscaler, translating inbound webhook events into isolated execution tasks with micro-latency queueing and fine-grained credit accounting.

```mermaid
sequenceDiagram
    autonumber
    participant GH as GitHub Actions (Workflow Queue)
    participant Webhook as hexaqueue-server (GitHub Webhook Ingress)
    participant Scheduler as hexaqueue-server (Scheduler & Runner Pool)
    participant Worker as hexaqueue-worker (Ephemeral Runner Node)

    Note over GH,Webhook: 1. Workflow Job Queued
    GH->>Webhook: POST /webhooks/github (workflow_job.queued)
    Webhook->>Webhook: Verify HMAC-SHA256 signature
    Webhook->>Scheduler: Evaluate Labels & Hardware Claims

    Note over Scheduler,Worker: 2. JIT Token Minting & Placement
    Scheduler->>GH: Mint Single-Use JIT Config (generate-jitconfig)
    Scheduler->>Worker: Dispatch JobSpec (./run.sh --jitconfig ... --once)

    Note over GH,Worker: 3. Execution & Zero-Trust Teardown
    Worker->>GH: Connect and execute workflow job
    Worker->>Scheduler: Workflow Complete (Wipe NVMe scratch)
    Scheduler->>GH: Publish Check Run Step Summary & HQ Credit Burn
```

---

## 🔑 GitHub App Setup & Permissions

To authenticate and manage Just-In-Time (JIT) ephemeral runners, register a GitHub App in your organization or user account:

1. **Repository / Organization Permissions**:
   - `Actions`: **Read & write** (for generating JIT runner registration configurations)
   - `Administration`: **Read & write** (for registering and deregistering runners)
   - `Checks`: **Read & write** (for publishing execution performance annotations)
   - `Metadata`: **Read-only**

2. **Subscribe to Webhook Events**:
   - `Workflow job` (emits `queued`, `in_progress`, and `completed` events)

3. **Webhook URL & Secret**:
   - URL: `https://<your-hexaqueue-server>/webhooks/github`
   - Content type: `application/json`
   - Secret: Configure a cryptographically secure token and supply it to Hexaqueue via `HEXAQUEUE_WEBHOOK_SECRET_GITHUB`.

---

## 🏷️ Label-to-Hardware Translation

Hexaqueue eliminates manual runner fleet management by automatically mapping GitHub Actions `runs-on` labels to pure domain [`ResourceRequirements`](../packages/hexaqueue_core/README.md):

| Label Syntax | Parsed Claim | Example Label |
|---|---|---|
| `(\d+)-cores?`, `cpu-(\d+)` | CPU Core Count | `16-cores`, `cpu-8`, `4-cpu` |
| `(\d+)gb(?:-ram)?`, `ram-(\d+)gb` | Memory (RAM) | `64gb`, `ram-32gb` |
| `gpu-(\w+)`, or GPU model keyword | Dedicated GPU Accelerator | `gpu-h100`, `a100`, `l4`, `t4`, `rtx4090` |
| `(\d+)-gpu-(\w+)` | Multi-GPU Accelerator Pool | `4-gpu-a100`, `2x-gpu-h100` |
| `(\d+)gb-scratch`, `scratch-(\d+)gb` | Local NVMe Scratch Space | `100gb-scratch`, `scratch-50gb` |
| `(\d+)h-walltime`, `(\d+)m-walltime` | Execution Time Limit (SIGKILL) | `2h-walltime`, `90m-walltime` |

### Example GitHub Actions Workflow

```yaml
name: Distributed GPU Training
on: [push]

jobs:
  train:
    runs-on: [self-hosted, linux, 16-cores, 64gb, gpu-h100, 100gb-scratch, 2h-walltime]
    steps:
      - uses: actions/checkout@v4
      - name: Run PyTorch Benchmark
        run: python train.py --epochs 10
```

---

## 🛡️ Single-Job Isolation & Ephemeral Teardown

1. **Zero Cross-Job Contamination**:
   - Runners are spawned with `--once` and bound strictly to the JIT configuration blob.
   - Once the job finishes, the runner daemon exits immediately.
2. **Scratch Disk Sanitization**:
   - Local NVMe scratch volumes mounted at `_work` are wiped immediately following process termination.
   - Memory and GPU VRAM are cleared before the node is returned to the allocatable cluster pool.

---

## ⚡ Pre-Warmed Pools for Micro-Latency

For high-frequency test suites (such as pull request smoke tests), latency can be eliminated using pre-warmed static pools:

```python
from hexaqueue.github_runner import (
    DynamicGitHubRunnerAutoscaler,
    WarmPoolConfig,
)

# Maintain 3 warm idle runners ready to pick up jobs instantaneously
autoscaler.register_warm_pool(
    WarmPoolConfig(
        pool_id="fast-ci",
        labels=["self-hosted", "fast-ci"],
        min_idle=3,
        max_capacity=10,
    )
)
```

---

## 📊 Two-Way Observability & Step Summaries

Upon workflow completion, Hexaqueue posts an execution summary to the GitHub Check Run:

```markdown
### ⚡ Hexaqueue Runner Execution Report

| Metric | Value |
|---|---|
| **Hexaqueue Job ID** | `job-gh-99881` |
| **Hexaqueue Run ID** | `run-gh-my-repo-4412` |
| **Status** | `COMPLETED` |
| **Duration** | `42.50s` |
| **Credits Consumed** | `0.0000 HQ` |
| **Infrastructure Cost** | `$0.00 (Verified $0.00 Free Tier)` |

**Resource Allocation Details:**
- **Cloud Provider**: `OCI`
- **Cluster Node**: `hq-gh-oci-my-repo-99881-a1b2`
- **Single-Job Isolation**: Verified (Scratch wiped upon exit)
```

---

## 🌐 Multi-CSP Free-Tier Mesh Autoscaling ($0.00 Spend Invariant)

To burst GitHub Actions runner matrices beyond the default 2 vCPU limit without incurring any cloud expenditure, configure `DynamicGitHubRunnerAutoscaler` with the federated `MultiCspFreeTierGovernor`:

```python
from hexaqueue_core.adapters.freetier.governor import MultiCspFreeTierGovernor
from hexaqueue_github_runner import (
    DynamicGitHubRunnerAutoscaler,
    GitHubApiClient,
    GitHubAppCredentials,
    GitHubWebhookAdapter,
    HmacSha256WebhookVerifier,
)

credentials = GitHubAppCredentials(...)
api_client = GitHubApiClient(credentials=credentials)
governor = MultiCspFreeTierGovernor()

# Configure autoscaler with zero-cost multi-cloud bursting
autoscaler = DynamicGitHubRunnerAutoscaler(
    api_client=api_client,
    free_tier_governor=governor,
)
```

### Free-Tier Capacity Pooling Across Clouds

The federated mesh pools perpetual Always-Free tiers across OCI, GCP, AWS, Azure, and Local workstation workers into an aggregate compute cluster:

| Provider | Free-Tier Allocation | Sizing & Architecture | Target CI Label |
|---|---|---|---|
| **Oracle Cloud (OCI)** | 4 vCPUs / 24 GB RAM / 200 GB Storage | Ampere A1 ARM64 | `runs-on: [self-hosted, arm64, 4-cores]` |
| **Google Cloud (GCP)** | 2 vCPUs / 1 GB RAM / 30 GB Storage | e2-micro x86_64 | `runs-on: [self-hosted, gcp, 2-cores]` |
| **Amazon Web Services (AWS)** | 1 vCPU / 1 GB RAM / 30 GB Storage | t2/t3.micro x86_64 | `runs-on: [self-hosted, aws, 1-core]` |
| **Microsoft Azure** | 1 vCPU / 1 GB RAM / 32 GB Storage | B1s x86_64 | `runs-on: [self-hosted, azure, 1-core]` |
| **Local Workstation** | Host Cores / 2 GB RAM / 50 GB Storage | Local Bare-Metal Sandbox | `runs-on: [self-hosted, local, 2-cores]` |

### Matrix Fan-Out Example

```yaml
name: Cross-Platform Matrix Test
on: [push]

jobs:
  test:
    strategy:
      matrix:
        include:
          - target: arm64
            labels: [self-hosted, arm64, 4-cores, 8gb-ram] # Dispatched to OCI
          - target: linux-gcp
            labels: [self-hosted, gcp, 2-cores]            # Dispatched to GCP
          - target: linux-aws
            labels: [self-hosted, aws, 1-core]             # Dispatched to AWS
          - target: linux-azure
            labels: [self-hosted, azure, 1-core]           # Dispatched to Azure
          - target: local-worker
            labels: [self-hosted, local, 2-cores]          # Dispatched to Local
    runs-on: ${{ matrix.labels }}
    steps:
      - uses: actions/checkout@v4
      - name: Run Test Suite
        run: pytest -v
```

All 5 matrix jobs run simultaneously across the free cloud tiers (10 total vCPUs pooled) at verified $0.00 cost, with single-use JIT tokens and immediate quota recycling upon job exit.
