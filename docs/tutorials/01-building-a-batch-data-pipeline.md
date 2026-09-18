# Tutorial 1: Building a Distributed Batch Data Pipeline with Hexaqueue

Welcome to the foundational tutorial for **Hexaqueue**!

In this guide, you will learn how to build, test, and orchestrate a multi-stage **Directed Acyclic Graph (DAG)** compute workflow using Hexaqueue's **Hexagonal Architecture (Ports & Adapters)** and the `hq` developer CLI with **$0 cloud spend** on your local machine.

By the end of this tutorial, you will have:

- Built a modular, zero-dependency batch data processing domain model.
- Created secondary port interfaces and concrete compute adapters.
- Formulated a multi-stage declarative YAML workflow DAG with conditional triggers and resource constraints.
- Submitted, monitored, and streamed logs interactively using the `hq` CLI developer toolchain.
- Enforced 100% test parity and architectural contracts.

---

## 1. Project Architecture

Hexaqueue enforces strict separation of concerns across hexagonal layers:

```text
examples/data-pipeline/
├── pipelines/
│   └── etl_workflow.yaml         # Declarative DAG Pipeline Definition
├── src/data_pipeline/
│   ├── domain/                   # 1. Pure Python Domain Entities & Value Objects
│   │   ├── __init__.py
│   │   └── models.py
│   ├── ports/                    # 2. Abstract Port Interfaces (Processors & Workflows)
│   │   ├── __init__.py
│   │   └── processor.py
│   ├── adapters/                 # 3. Concrete Primary & Secondary Adapters
│   │   ├── __init__.py
│   │   └── local.py
│   └── infra/                    # 4. Pipeline Assembly & Execution Wiring
│       ├── __init__.py
│       └── runner.py
└── tests/
    └── unit/                     # 1:1 Parity Unit Tests
```

---

## 2. Defining Domain Entities

Our data processing domain defines data records and statistical summaries with strict validation invariants using Pydantic.

Create `src/data_pipeline/domain/models.py`:

```python
"""Domain models for data processing tutorial."""

from typing import Self
from pydantic import BaseModel, ConfigDict, Field, model_validator


class DataRecord(BaseModel):
    """Single unit of processed data.

    Args:
        id: Unique positive numerical record identifier.
        val: Numerical payload value.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(gt=0, description="Record identifier")
    val: float = Field(description="Numerical value")


class SummaryResult(BaseModel):
    """Summary statistics aggregated from records.

    Args:
        count: Total number of processed records.
        mean: Calculated arithmetic mean.
        total: Aggregated numerical sum.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    count: int = Field(ge=0, description="Total count")
    mean: float = Field(description="Mean value")
    total: float = Field(description="Total sum")

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate math consistency across count, total, and mean."""
        if self.count > 0:
            expected = round(self.total / self.count, 4)
            if round(self.mean, 4) != expected:
                msg = f"Mean {self.mean} does not match total/count {expected}"
                raise ValueError(msg)
        return self


__all__ = [
    "DataRecord",
    "SummaryResult",
]
```

---

## 3. Creating Abstract Ports & Adapters

Decouple the data transformation contract from execution hardware by defining `DataProcessorPort`.

### Abstract Port (`src/data_pipeline/ports/processor.py`)

```python
"""Port interface for data batch processing."""

from abc import ABC, abstractmethod
from data_pipeline.domain.models import DataRecord, SummaryResult


class DataProcessorPort(ABC):
    """Abstract processor interface for data operations."""

    @abstractmethod
    def compute_summary(self, records: list[DataRecord]) -> SummaryResult:
        """Compute aggregate summary from records."""

    @abstractmethod
    def compute_squares(self, records: list[DataRecord]) -> list[float]:
        """Compute square features."""


__all__ = [
    "DataProcessorPort",
]
```

### Local Memory Adapter (`src/data_pipeline/adapters/local.py`)

```python
"""Local memory data processor adapter."""

from data_pipeline.domain.models import DataRecord, SummaryResult
from data_pipeline.ports.processor import DataProcessorPort


class LocalDataProcessorAdapter(DataProcessorPort):
    """In-memory data processor implementation."""

    def compute_summary(self, records: list[DataRecord]) -> SummaryResult:
        """Compute aggregate summary from records."""
        if not records:
            return SummaryResult(total=0.0, count=0, mean=0.0)
        total = sum(r.val for r in records)
        count = len(records)
        return SummaryResult(total=total, count=count, mean=total / count)

    def compute_squares(self, records: list[DataRecord]) -> list[float]:
        """Compute square features."""
        return [r.val**2 for r in records]


__all__ = [
    "LocalDataProcessorAdapter",
]
```

---

## 4. Declarative DAG Pipeline Specification

Hexaqueue workflows are defined declaratively with resource allocations, timeouts, and dependency graphs.

To make local experimentation observable, we introduce deliberate **artificial delays** (`time.sleep(1.5)`) across each stage. Without delays, tiny local tasks finish in milliseconds, making it impossible to observe in-flight states or test CLI status inspection tools. With ~1.5s per stage, the entire pipeline executes in ~4.5 seconds—fast enough for rapid iteration, yet spacious enough to watch tasks transition from pending to running to completed.

Create `pipelines/etl_workflow.yaml`:

```yaml
run:
  id: "demo-etl-run"
  name: "Batch ETL & Data Analysis Pipeline"
  tags:
    - "tutorial"
    - "etl"

jobs:
  - id: "stage1-extract"
    name: "Extract Source Records"
    command: "python -c \"import json, os, time; time.sleep(1.5); os.makedirs('/tmp/demo_etl', exist_ok=True); json.dump([{'id': i, 'val': i * 10} for i in range(1, 6)], open('/tmp/demo_etl/raw.json', 'w')); print('Extracted 5 records')\""
    resources:
      cpus: 1
      ram_mb: 512
      scratch_mb: 100
      walltime_seconds: 15

  - id: "stage2-transform-a"
    name: "Calculate Summary Metrics"
    command: "python -c \"import json, time; time.sleep(1.5); records = json.load(open('/tmp/demo_etl/raw.json')); total = sum(r['val'] for r in records); json.dump({'total': total, 'count': len(records)}, open('/tmp/demo_etl/summary.json', 'w')); print(f'Transformed metrics: Total={total}')\""
    depends_on: "stage1-extract"
    resources:
      cpus: 1
      ram_mb: 512
      scratch_mb: 100
      walltime_seconds: 15

  - id: "stage2-transform-b"
    name: "Generate Squared Features"
    command: "python -c \"import json, time; time.sleep(1.5); records = json.load(open('/tmp/demo_etl/raw.json')); squares = [r['val']**2 for r in records]; json.dump({'squares': squares}, open('/tmp/demo_etl/squares.json', 'w')); print(f'Calculated {len(squares)} squared features')\""
    depends_on: "stage1-extract"
    resources:
      cpus: 1
      ram_mb: 512
      scratch_mb: 100
      walltime_seconds: 15

  - id: "stage3-load-report"
    name: "Aggregate Final Report"
    command: "python -c \"import json, time; time.sleep(1.5); s = json.load(open('/tmp/demo_etl/summary.json')); sq = json.load(open('/tmp/demo_etl/squares.json')); print(f'ETL Completed! Total: {s[\"total\"]}, Mean: {s[\"total\"]/s[\"count\"]}, Squares: {sq[\"squares\"]}')\""
    depends_on:
      - "stage2-transform-a"
      - "stage2-transform-b"
    resources:
      cpus: 1
      ram_mb: 512
      scratch_mb: 100
      walltime_seconds: 15
```

---

## 5. Executing & Monitoring via `hq` CLI

Submit and monitor the DAG pipeline on your local machine using the built-in `hq` CLI:

### 1. Submit and Watch DAG Execution Live

```bash
uv run hq run submit examples/data-pipeline/pipelines/etl_workflow.yaml --watch
```

Output:
```text
✓ Run 'demo-etl-run' submitted (4 jobs)
Run completed with status: SUCCEEDED
                         Run Status: demo-etl-run
┏━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┓
┃ Run ID       ┃ State ┃ Outcome   ┃ Total ┃ Completed ┃ Failed ┃ Pending ┃
┡━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━┩
│ demo-etl-run │ DONE  │ SUCCEEDED │   4   │     4     │   0    │    0    │
└──────────────┴───────┴───────────┴───────┴───────────┴────────┴─────────┘
```

### 2. Free-Tier Safety Mode ($0 Cloud Spend Guard)

Hexaqueue enforces automated guardrails against unexpected cloud spend via `--free-tier`. When activated, task requests are validated against Cloud Service Provider free-tier quotas, and a live Quota Burn Meter is rendered:

```bash
uv run hq run submit examples/data-pipeline/pipelines/etl_workflow.yaml --watch --free-tier
```

Output:
```text
✓ Run 'demo-etl-run' submitted (4 jobs)
Run completed with status: SUCCEEDED
                [FREE TIER ACTIVE] Run Status: demo-etl-run
┏━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┓
┃ Run ID       ┃ State ┃ Outcome   ┃ Total ┃ Completed ┃ Failed ┃ Pending ┃
┡━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━┩
│ demo-etl-run │ DONE  │ SUCCEEDED │   4   │     4     │   0    │    0    │
└──────────────┴───────┴───────────┴───────┴───────────┴────────┴─────────┘
 Free-Tier Quota Burn Meter (Local Container / Developer Sandbox)
┏━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━┓
┃ Resource ┃ Allocated ┃ Ceiling ┃ Utilization ┃ Status ┃
┡━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━┩
│ CPU      │   0 cores │ 2 cores │        0.0% │   OK   │
│ RAM      │      0 MB │ 2048 MB │        0.0% │   OK   │
│ Storage  │      0 MB │ 5120 MB │        0.0% │   OK   │
└──────────┴───────────┴─────────┴─────────────┴────────┘
```

### 3. Queue Explainability & Scheduling Diagnostics

Hexaqueue provides full explainability for every scheduling decision:

```bash
# Get a concise 1-line reason why a job is waiting
uv run hq why stage3-load-report

# Inspect rich priority breakdown, fair-share deficit, and dependency blockers
uv run hq explain stage3-load-report

# Inspect cluster fair-share tree hierarchy and usage decay
uv run hq fairshare
```

### 4. Inspect Individual Job Status & Captured Logs

```bash
# Query individual job outcome
uv run hq status stage2-transform-a

# Tail captured stdout/stderr stream logs
uv run hq logs stage1-extract
```

---

## 6. Running Unit & Parity Tests

Verify 1:1 architecture symmetry, zero-defect type safety, and 100% test coverage using the unified Hexaqual test runner:

```bash
uv run hexaqual test run -e data-pipeline
```

---

## 7. Summary & Next Steps

### What You've Learned 🎓
- How to structure clean, framework-agnostic batch data processing models.
- How Hexaqueue resolves DAG dependencies and schedules parallel ready tasks automatically.
- How deliberate artificial delays provide an observable execution window for CLI diagnostics.
- How Free-Tier Safety Mode (`--free-tier`) guards developer workflows against unintended cloud charges.
- How to inspect scheduling rationale transparently using `hq why` and `hq explain`.

### Up Next 🚀
- **Tutorial 2: Parallel Monte-Carlo Simulation & Multi-Variable Smoothing**
- **Tutorial 3: Resolving the 100-Slot Monopoly with Fair-Share & Controlled Preemption**
