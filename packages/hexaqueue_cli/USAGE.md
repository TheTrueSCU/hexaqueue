# Hexaqual Quality Suite & CLI Catalog (`hq`)

> Canonical developer command reference and CLI catalog automatically generated from the complete command hierarchy.

---

## 🏛️ Dogfooding Hexagonal Architecture

`hexaqual` is built strictly according to Hexagonal Architecture design principles:
- **`domain/`**: Pure data contracts (`PrSummary`, `CheckRunFinding`, `ReviewThread`, `OutputFormat`).
- **`ports/`**: Clean interface contracts (`GitHubApiPort`, `GovernancePresenterPort`, `ToolRunnerPort`, `PyPiClientPort`).
- **`adapters/`**: Pluggable presenters (`rich`, `json`, `plain`), subcommands, and runners.
- **`cli/`**: Unified Typer CLI driving adapter (`hexaqual`).
- **`infra/`**: Command dispatchers, handlers, and execution orchestration.
- **`utils/`**: Workspace discovery, AST parsing, and package graph resolvers.

---

## ⚙️ Output Presentation Formats

All inspection commands support `--format / -f`:
- **`auto` (default)**: Automatically outputs interactive ANSI tables/panels when attached to a terminal TTY, and switches to clean, tab-delimited plain text (`TSV`) when standard output is piped into Unix filters (`grep`, `awk`, `cut`, `xargs`, etc.).
- **`rich`**: Interactive Rich tables and color-coded status badges.
- **`json`**: Structured JSON for automation, CI scripts, and AI agents.
- **`plain`**: Machine-readable TSV stream.

---

## 🚀 Unified Root Entrypoint (`hq`)

```text
Usage: hq [OPTIONS] COMMAND [ARGS]...

 Hexaqueue - Cloud-Agnostic HPC Batch Scheduler and Distributed Job
 Orchestrator

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --install-completion          Install completion for the current shell.      │
│ --show-completion             Show completion for the current shell, to copy │
│                               it or customize the installation.              │
│ --help                        Show this message and exit.                    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ status    Check status of a run or job.                                      │
│ logs      View stdout and stderr logs for a job.                             │
│ cancel    Cancel an active pipeline run.                                     │
│ run       Pipeline run management commands.                                  │
│ workflow  Hexaflow distributed workflow orchestration and cluster scheduling │
│           commands.                                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

---

## 🛠️ Complete Subcommand Tree Reference

### `hq cancel`

```text
Usage: hq cancel [OPTIONS] {run_id}

 Cancel an active pipeline run.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    run_id      <str>  Run ID to cancel [required]                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq logs`

```text
Usage: hq logs [OPTIONS] {job_id}

 View stdout and stderr logs for a job.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  Job ID to fetch logs for [required]                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --follow  -f        Follow stream output                                     │
│ --help              Show this message and exit.                              │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq run`

```text
Usage: hq run [OPTIONS] COMMAND [ARGS]...

 Pipeline run management commands.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ submit  Submit a DAG pipeline definition file.                               │
╰──────────────────────────────────────────────────────────────────────────────╯
```

#### `hq run submit`

```text
Usage: hq run submit [OPTIONS] {spec_path}

 Submit a DAG pipeline definition file.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    spec_path      <path>  Path to pipeline YAML spec [required]            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --watch   -w             Watch run execution until completion                │
│ --format  -f      <str>  Output presentation format (table, json, markdown,  │
│                          rich, plain, auto).                                 │
│                          [default: table]                                    │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq status`

```text
Usage: hq status [OPTIONS] {target_id}

 Check status of a run or job.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    target_id      <str>  Run ID or Job ID to inspect [required]            │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --format  -f      <str>  Output presentation format (table, json, markdown,  │
│                          rich, plain, auto).                                 │
│                          [default: table]                                    │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq workflow`

```text
Usage: hq workflow [OPTIONS] COMMAND [ARGS]...

 Hexaflow distributed workflow orchestration and cluster scheduling commands.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ submit  Submit a workflow definition for distributed cluster execution.      │
│ status  Inspect status, checkpoints, and staged artifacts for a workflow     │
│         run.                                                                 │
│ resume  Resume execution of a suspended workflow run from its latest         │
│         checkpoints.                                                         │
│ abort   Abort an active or suspended workflow, unwinding step compensations  │
│         in reverse order.                                                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

#### `hq workflow abort`

```text
Usage: hq workflow abort [OPTIONS] {run_id} {target}

 Abort an active or suspended workflow, unwinding step compensations in reverse
 order.

 Args:
 run_id: Run identifier to abort.
 target: Workflow file specifier containing compensations.
 db_path: SQLite state database path.
 format_type: Output presentation format.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    run_id      <str>  Workflow run identifier to abort [required]          │
│ *    target      <str>  Path to workflow file [required]                     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --db              <str>  Path to SQLite state database                       │
│                          [default: .hexaflow/state.db]                       │
│ --format  -f      <str>  Output presentation format (table, json, markdown,  │
│                          rich, plain, auto).                                 │
│                          [default: table]                                    │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

#### `hq workflow in`

```text
Usage: hq workflow [OPTIONS] COMMAND [ARGS]...
Try 'hq workflow --help' for help.
╭─ Error ──────────────────────────────────────────────────────────────────────╮
│ No such command 'in'.                                                        │
╰──────────────────────────────────────────────────────────────────────────────╯
```

#### `hq workflow resume`

```text
Usage: hq workflow resume [OPTIONS] {run_id} {target}

 Resume execution of a suspended workflow run from its latest checkpoints.

 Args:
 run_id: Suspended run identifier.
 target: Target workflow file specifier.
 inputs: Optional patch inputs.
 skip_steps: Optional step names to skip.
 db_path: SQLite state database path.
 format_type: Output presentation format.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    run_id      <str>  Suspended workflow run identifier [required]         │
│ *    target      <str>  Path to workflow file, e.g. 'pipeline.py' or         │
│                         'pipeline.py:my_flow'                                │
│                         [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --inputs  -i      <str>  Patch inputs for resuming step frontier             │
│ --skip            <str>  Step names to explicitly skip                       │
│ --db              <str>  Path to SQLite state database                       │
│                          [default: .hexaflow/state.db]                       │
│ --format  -f      <str>  Output presentation format (table, json, markdown,  │
│                          rich, plain, auto).                                 │
│                          [default: table]                                    │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

#### `hq workflow status`

```text
Usage: hq workflow status [OPTIONS] {run_id}

 Inspect status, checkpoints, and staged artifacts for a workflow run.

 Args:
 run_id: Run identifier to query.
 db_path: SQLite state store database path.
 format_type: Output presentation format.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    run_id      <str>  Workflow execution run identifier to inspect         │
│                         [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --db              <str>  Path to SQLite state database                       │
│                          [default: .hexaflow/state.db]                       │
│ --format  -f      <str>  Output presentation format (table, json, markdown,  │
│                          rich, plain, auto).                                 │
│                          [default: table]                                    │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

#### `hq workflow submit`

```text
Usage: hq workflow submit [OPTIONS] {target}

 Submit a workflow definition for distributed cluster execution.

 Args:
 target: Target file path or specifier.
 inputs: Optional JSON inputs string.
 db_path: SQLite state store database path.
 watch: Whether to block and watch until terminal completion.
 format_type: Output presentation format.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    target      <str>  Path to workflow file, e.g. 'pipeline.py' or         │
│                         'pipeline.py:my_flow'                                │
│                         [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --inputs  -i      <str>  JSON dictionary of initial inputs                   │
│ --db              <str>  Path to SQLite state database                       │
│                          [default: .hexaflow/state.db]                       │
│ --watch   -w             Watch workflow execution until completion           │
│ --format  -f      <str>  Output presentation format (table, json, markdown,  │
│                          rich, plain, auto).                                 │
│                          [default: table]                                    │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```
