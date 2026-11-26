# Tutorial 0: Quickstart (5-Minute Local Cluster)

Get Hexaqueue running on your local machine with zero cloud spend, start a local controller and worker, and execute your first distributed task DAG in under five minutes.

---

## 1. Prerequisites

Ensure you have [Astral `uv`](https://github.com/astral-sh/uv) installed on your system:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

---

## 2. Clone & Sync Dependencies

Clone the Hexaqueue repository and sync all packages:
```bash
git clone https://github.com/TheTrueSCU/hexaqueue.git ~/hexaqueue
cd ~/hexaqueue
uv sync --all-packages --all-extras
```

---

## 3. Configure Local Development Environment

Copy the example template to `.env.local`:
```bash
cp .env.example .env.local
```

For local testing, configure `.env.local` for both client (`8000`) and internal worker API (`8001`):
```ini
HEXAQUEUE_SERVER_URL=http://127.0.0.1:8000
HEXAQUEUE_WORKER_PORT=8001
HEXAQUEUE_API_TOKEN=dev-secret-token
HEXAQUEUE_FREE_TIER=true
```

---

## 4. Start Local Controller & Worker

### Terminal 1: Start Hexaqueue Controller
```bash
HEXAQUEUE_WORKER_PORT=8001 uv run hq server start --host 127.0.0.1 --port 8000
```
You should see:
```text
[Hexaqueue] Starting controller on http://127.0.0.1:8000 ...
[Hexaqueue] Health check: OK
```

### Terminal 2: Start Local Worker Daemon
```bash
HEXAQUEUE_CONTROLLER_URL=http://127.0.0.1:8001 uv run python -m hexaqueue_worker.adapters.agent
```

---

## 5. Submit Your First Distributed Task

### Terminal 3: Verify Status & Submit Run
Verify the controller is reachable and inspect cluster status:
```bash
uv run hq cluster status
```

Create a simple workflow definition `quickstart.yaml`:
```yaml
run:
  id: "quickstart-run-01"
  name: "My First Hexaqueue DAG"

jobs:
  - id: "step-1"
    name: "Generate Numbers"
    command: "python"
    args: ["-c", "print('Generating numbers 1 through 10...')"]
    resources:
      cpus: 1
      ram_mb: 512

  - id: "step-2"
    name: "Compute Sum"
    command: "python"
    args: ["-c", "print('Computed sum: 55')"]
    depends_on:
      - "step-1"
    resources:
      cpus: 1
      ram_mb: 512
```

Submit and watch the execution:
```bash
uv run hq run submit quickstart.yaml --watch
```

You will see the job transition through `RUNNING` to `DONE`, successfully executing your first DAG!
