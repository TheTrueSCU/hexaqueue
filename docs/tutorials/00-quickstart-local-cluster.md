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

For local testing, the default settings in `.env.local` work out-of-the-box:
```ini
HEXAQUEUE_SERVER_URL=http://127.0.0.1:8000
HEXAQUEUE_API_TOKEN=dev-secret-token
HEXAQUEUE_FREE_TIER=true
```

---

## 4. Start Local Controller & Worker

### Terminal 1: Start Hexaqueue Controller
```bash
uv run hq server start --host 127.0.0.1 --port 8000
```
You should see:
```text
[Hexaqueue] Starting controller on http://127.0.0.1:8000 ...
[Hexaqueue] Health check: OK
```

### Terminal 2: Start Local Worker Daemon
```bash
uv run hq worker start --server-url http://127.0.0.1:8000 --port 8001
```

---

## 5. Submit Your First Distributed Task

### Terminal 3: Verify Status & Submit Run
Verify the controller recognizes the worker:
```bash
uv run hq status
```

Create a simple workflow definition `quickstart.yaml`:
```yaml
run_spec:
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
    resources:
      cpus: 1
      ram_mb: 512

dependencies:
  "step-2": ["step-1"]
```

Submit and stream the execution:
```bash
uv run hq run submit quickstart.yaml --stream
```

You will see the job transition through `RUNNING` to `DONE`, successfully executing your first DAG!
