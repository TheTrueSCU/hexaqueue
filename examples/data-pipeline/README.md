# data-pipeline

> Hexaqueue Batch Data Processing & Scientific Workflow Tutorial

Built with **[Hexaqueue](https://github.com/TheTrueSCU/hexaqueue)** — The Cloud-Agnostic HPC Batch Scheduler and Distributed Job Orchestrator.

## Architecture

This project illustrates a complete multi-stage DAG data pipeline executed across decoupled hexagonal components:

```text
examples/data-pipeline/
├── pipelines/
│   └── etl_workflow.yaml         # Declarative DAG Pipeline Definition
├── src/data_pipeline/
│   ├── domain/                   # Domain models & transformations
│   │   ├── __init__.py
│   │   └── models.py
│   ├── ports/                    # Port interfaces
│   │   ├── __init__.py
│   │   └── processor.py
│   ├── adapters/                 # Concrete runtime processors
│   │   ├── __init__.py
│   │   └── local.py
│   └── infra/                    # Pipeline runner & bootstrap
│       ├── __init__.py
│       └── runner.py
└── tests/
    └── unit/                     # 1:1 Unit Tests
```

## Getting Started

```bash
# 1. Run pipeline via hq CLI
uv run hq run submit pipelines/etl_workflow.yaml --watch

# 2. Inspect run and job execution logs
uv run hq status demo-etl-run
uv run hq logs stage1-extract

# 3. Run unit tests
uv run pytest
```
