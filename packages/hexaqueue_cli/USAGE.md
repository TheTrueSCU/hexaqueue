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
│ submit      Submit a workload run or suite definition file.                  │
│ status      Check status of a run or job.                                    │
│ logs        View stdout and stderr logs for a job.                           │
│ cancel      Cancel an active pipeline run or individual job.                 │
│ hold        Place an administrative hold on a pending job.                   │
│ release     Release an administrative hold on a job back to the queue.       │
│ stat        Display high-level cluster state and backlog statistics.         │
│ nodes       Display compute worker nodes telemetry and accelerator status.   │
│ quota       Inspect hierarchical fair-share tree, historical usage, and      │
│             quota allowances.                                                │
│ top         Interactive live cluster and queue monitoring dashboard.         │
│ exec        Spawn an interactive PTY session inside a running job            │
│             environment.                                                     │
│ attach      Attach an interactive bash shell to a running job.               │
│ why         Explain why a job is currently waiting in the queue.             │
│ explain     Display rich priority math and resource blocker breakdown for a  │
│             job.                                                             │
│ fairshare   Inspect hierarchical fair-share tree, historical usage, and      │
│             decay factors.                                                   │
│ run         Pipeline run management commands.                                │
│ workflow    Hexaflow distributed workflow orchestration and cluster          │
│             scheduling commands.                                             │
│ suite       Manage and execute hierarchical suite workloads and parameter    │
│             sweeps                                                           │
│ collateral  Manage, stage, and inspect collateral artifacts and binaries     │
│ node        Inspect worker nodes and establish administrative bastion        │
│             sessions                                                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

---

## 🛠️ Complete Subcommand Tree Reference

### `hq attach`

```text
Usage: hq attach [OPTIONS] {job_id}

 Attach an interactive bash shell to a running job.

 Args:
     job_id: Target running job identifier.
     user: Requesting user identity for RBAC validation.

 Notes/Architectural Intent:
     Convenience alias launching an interactive bash terminal inside the target
 job.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  Job ID to attach interactive shell to [required]     │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --user  -u      <str>  Requesting username [default: default]                │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq cancel`

```text
Usage: hq cancel [OPTIONS] {target_id}

 Cancel an active pipeline run or individual job.

 Args:
     target_id: Identifier of the run or job to cancel.
     admin: Assert explicit administrative elevation.
     user: Requesting user identity.

 Notes/Architectural Intent:
     Attempts run cancellation first, falling back to individual job
 cancellation.
     Requires explicit --admin elevation for cross-user mutations.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    target_id      <str>  Run ID or Job ID to cancel [required]             │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --admin                 Assert explicit administrative elevation for         │
│                         cross-user cancellation                              │
│ --user   -u      <str>  Requesting user identity [default: default]          │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq collateral`

```text
Usage: hq collateral [OPTIONS] COMMAND [ARGS]...

 Manage, stage, and inspect collateral artifacts and binaries

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ push  Stage and register a collateral artifact for compute execution.        │
╰──────────────────────────────────────────────────────────────────────────────╯
```

#### `hq collateral push`

```text
Usage: hq collateral push [OPTIONS] {file_path}

 Stage and register a collateral artifact for compute execution.

 Args:
     file_path: Local file path to stage.
     name: Logical name override.
     tier: Retention tier string.
     kind: Collateral classification kind.
     user: Submitting user identity.
     admin: Administrative elevation flag.

 Notes/Architectural Intent:
     Calculates cryptographic SHA-256 digest and stages metadata through
     the unified execution pipeline.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    file_path      <path>  Path to local collateral file or bundle to stage │
│                             [required]                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --name   -n      <str>  Override logical collateral name (defaults to        │
│                         filename)                                            │
│ --tier           <str>  Collateral retention tier (TEMPORARY, PERMANENT)     │
│                         [default: TEMPORARY]                                 │
│ --kind           <str>  Collateral kind (BUNDLE, OS_IMAGE, CONTAINER_IMAGE,  │
│                         TEST_BINARY, DATASET)                                │
│                         [default: BUNDLE]                                    │
│ --user   -u      <str>  Submitting user identity [default: default]          │
│ --admin                 Assert explicit administrative elevation             │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq decay`

```text
Usage: hq [OPTIONS] COMMAND [ARGS]...
Try 'hq --help' for help.
╭─ Error ──────────────────────────────────────────────────────────────────────╮
│ No such command 'decay'.                                                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq exec`

```text
Usage: hq exec [OPTIONS] {job_id} {command}...

 Spawn an interactive PTY session inside a running job environment.

 Args:
     job_id: Target running job identifier.
     command: Command vector to execute in terminal PTY.
     user: Requesting user identity for RBAC validation.

 Notes/Architectural Intent:
     Connects local terminal to remote worker PTY master bridge with RBAC
 authorization.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    job_id       <str>  Job ID to execute command in [required]             │
│ *    command      <str>  Command vector to run inside job environment        │
│                          [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --user  -u      <str>  Requesting username [default: default]                │
│ --help                 Show this message and exit.                           │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq explain`

```text
Usage: hq explain [OPTIONS] {job_id}

 Display rich priority math and resource blocker breakdown for a job.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  Job ID to explain [required]                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --format  -f      <str>  Output presentation format (table, json, markdown,  │
│                          rich, plain, auto).                                 │
│                          [default: table]                                    │
│ --admin                  Assert explicit administrative elevation            │
│ --user    -u      <str>  Requesting username [default: default]              │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq fairshare`

```text
Usage: hq fairshare [OPTIONS]

 Inspect hierarchical fair-share tree, historical usage, and decay factors.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --format  -f      <str>  Output presentation format (table, json, markdown,  │
│                          rich, plain, auto).                                 │
│                          [default: table]                                    │
│ --admin                  Assert explicit administrative elevation            │
│ --user    -u      <str>  Requesting username [default: default]              │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq hold`

```text
Usage: hq hold [OPTIONS] {job_id}

 Place an administrative hold on a pending job.

 Args:
     job_id: Identifier of the pending job to hold.
     admin: Assert explicit administrative elevation.
     user: Requesting user identity.

 Notes/Architectural Intent:
     Transitions job state to BLOCKED and removes it from the scheduling
 candidate pool.
     Requires explicit --admin elevation for cross-user mutations.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  Job ID to place on administrative hold [required]    │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --admin                 Assert explicit administrative elevation for         │
│                         cross-user hold                                      │
│ --user   -u      <str>  Requesting user identity [default: default]          │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq logs`

```text
Usage: hq logs [OPTIONS] {job_id}

 View stdout and stderr logs for a job.

 Args:
     job_id: Target job identifier.
     follow: Stream chunks asynchronously in real time.
     tail: Number of historical lines to tail.

 Notes/Architectural Intent:
     Demuxes real-time stdout, stderr, and system log chunks with ANSI
 fidelity.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  Job ID to fetch logs for [required]                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --follow  -f             Follow stream output in real time                   │
│ --tail    -n      <int>  Number of lines to show from end                    │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq node`

```text
Usage: hq node [OPTIONS] COMMAND [ARGS]...

 Inspect worker nodes and establish administrative bastion sessions

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ list  List registered compute worker nodes and their telemetry pulses.       │
│ ssh   Open an administrative bastion terminal session on a worker node.      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

#### `hq node list`

```text
Usage: hq node list [OPTIONS]

 List registered compute worker nodes and their telemetry pulses.

 Args:
 format_type: Chosen serialization output format.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --format  -f      <str>  Output presentation format (table, json, markdown,  │
│                          rich, plain, auto).                                 │
│                          [default: table]                                    │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

#### `hq node ssh`

```text
Usage: hq node ssh [OPTIONS] {node_id}

 Open an administrative bastion terminal session on a worker node.

 Args:
     node_id: Target compute node worker ID.
     admin: Explicit administrative elevation confirmation.
     user: Requesting user identity.

 Notes/Architectural Intent:
     Enforces least privilege: connecting to worker node underlying
 infrastructure
     requires explicit administrative elevation (--admin).

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    node_id      <str>  Target worker node ID to attach to [required]       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --admin                 Assert explicit administrative elevation for bastion │
│                         shell access                                         │
│ --user   -u      <str>  Requesting user identity [default: default]          │
│ --help                  Show this message and exit.                          │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq nodes`

```text
Usage: hq nodes [OPTIONS]

 Display compute worker nodes telemetry and accelerator status.

 Args:
     format_type: Output format (table, json, markdown, plain, rich).

 Notes/Architectural Intent:
     Surfaces real-time hardware telemetry per worker compute node.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --format  -f      <str>  Output presentation format (table, json, markdown,  │
│                          rich, plain, auto).                                 │
│                          [default: table]                                    │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq quota`

```text
Usage: hq quota [OPTIONS]

 Inspect hierarchical fair-share tree, historical usage, and quota allowances.

 Args:
     format_type: Output format (table, json, markdown, plain, rich).

 Notes/Architectural Intent:
     Exposes fair-share tree and quota consumption under active multi-tenant
 hierarchy.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --format  -f      <str>  Output presentation format (table, json, markdown,  │
│                          rich, plain, auto).                                 │
│                          [default: table]                                    │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq release`

```text
Usage: hq release [OPTIONS] {job_id}

 Release an administrative hold on a job back to the queue.

 Args:
     job_id: Identifier of the blocked job to release.
     admin: Assert explicit administrative elevation.
     user: Requesting user identity.

 Notes/Architectural Intent:
     Transitions job back to PENDING and re-enqueues into the priority
 scheduler queue.
     Requires explicit --admin elevation for cross-user mutations.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  Job ID to release from administrative hold           │
│                         [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --admin                 Assert explicit administrative elevation for         │
│                         cross-user release                                   │
│ --user   -u      <str>  Requesting user identity [default: default]          │
│ --help                  Show this message and exit.                          │
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
│ cancel  Cancel an active pipeline run.                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

#### `hq run cancel`

```text
Usage: hq run cancel [OPTIONS] {run_id}

 Cancel an active pipeline run.

 Args:
     run_id: Pipeline run identifier.
     admin: Explicit administrative elevation.
     user: Requesting user identity.

 Notes/Architectural Intent:
     Enforces least privilege: administrative cancellation of runs submitted by
 other
     users requires explicit positive elevation (--admin).

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    run_id      <str>  Run ID to cancel [required]                          │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --admin                 Assert explicit administrative elevation for         │
│                         cross-user cancellation                              │
│ --user   -u      <str>  Requesting user identity [default: default]          │
│ --help                  Show this message and exit.                          │
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
│ --watch      -w             Watch run execution until completion             │
│ --free-tier                 Enable Free-Tier Safety Mode ($0.00 spend guard  │
│                             and strict resource clamping)                    │
│ --notify     -n      <str>  Notification targets (e.g. slack://...,          │
│                             pagerduty://...)                                 │
│ --notify-on          <str>  Lifecycle triggers (e.g. COMPLETED, FAILED,      │
│                             ERRORS, ALL)                                     │
│                             [default: ERRORS]                                │
│ --format     -f      <str>  Output presentation format (table, json,         │
│                             markdown, rich, plain, auto).                    │
│                             [default: table]                                 │
│ --help                      Show this message and exit.                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq scheduling`

```text
Usage: hq [OPTIONS] COMMAND [ARGS]...
Try 'hq --help' for help.
╭─ Error ──────────────────────────────────────────────────────────────────────╮
│ No such command 'scheduling'.                                                │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq sessions`

```text
Usage: hq [OPTIONS] COMMAND [ARGS]...
Try 'hq --help' for help.
╭─ Error ──────────────────────────────────────────────────────────────────────╮
│ No such command 'sessions'.                                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq stat`

```text
Usage: hq stat [OPTIONS]

 Display high-level cluster state and backlog statistics.

 Args:
     format_type: Output format (table, json, markdown, plain, rich).

 Notes/Architectural Intent:
     Provides rapid cluster health and queue backlog telemetry.

╭─ Options ────────────────────────────────────────────────────────────────────╮
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

 Args:
     target_id: Identifier of the run or job to inspect.
     format_type: Chosen serialization output format.

 Notes/Architectural Intent:
     Attempts run status resolution first, falling back to individual job
 inspection.

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

### `hq submit`

```text
Usage: hq submit [OPTIONS] {spec_path}

 Submit a workload run or suite definition file.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    spec_path      <path>  Path to pipeline YAML spec or suite definition   │
│                             file                                             │
│                             [required]                                       │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --watch      -w             Watch execution until completion                 │
│ --free-tier                 Enable Free-Tier Safety Mode                     │
│ --admin                     Assert explicit administrative elevation         │
│ --user       -u      <str>  Submitting user identity [default: default]      │
│ --format     -f      <str>  Output presentation format (table, json,         │
│                             markdown, rich, plain, auto).                    │
│                             [default: table]                                 │
│ --help                      Show this message and exit.                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq suite`

```text
Usage: hq suite [OPTIONS] COMMAND [ARGS]...

 Manage and execute hierarchical suite workloads and parameter sweeps

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                  │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────╮
│ run  Compile and submit a hierarchical suite workload.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

#### `hq suite run`

```text
Usage: hq suite run [OPTIONS] {suite_file}

 Compile and submit a hierarchical suite workload.

 Args:
     suite_file: Path to YAML or JSON suite specification.
     user: Submitting user identity.
     admin: Administrative elevation flag.
     format_type: Chosen serialization output format.

 Notes/Architectural Intent:
     Flattens multi-level parameter inheritance, matrix sweeps, and DAG
     dependencies, dispatching to the underlying execution engine.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    suite_file      <path>  Path to suite specification YAML or JSON file   │
│                              [required]                                      │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --user    -u      <str>  User identity submitting the suite workload         │
│                          [default: default]                                  │
│ --admin                  Assert explicit administrative elevation for        │
│                          privileged execution                                │
│ --format  -f      <str>  Output presentation format (table, json, markdown,  │
│                          rich, plain, auto).                                 │
│                          [default: table]                                    │
│ --help                   Show this message and exit.                         │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq sweeps`

```text
Usage: hq [OPTIONS] COMMAND [ARGS]...
Try 'hq --help' for help.
╭─ Error ──────────────────────────────────────────────────────────────────────╮
│ No such command 'sweeps'.                                                    │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq top`

```text
Usage: hq top [OPTIONS]

 Interactive live cluster and queue monitoring dashboard.

 Args:
     interval: Refresh period in seconds for live loop.
     once: Print static dashboard snapshot and exit immediately.

 Notes/Architectural Intent:
     Composes cluster summary, node telemetry, and top running/queued jobs into
 a reactive view.

╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --interval  -i      <float>  Refresh interval in seconds [default: 1.0]      │
│ --once      -1               Print dashboard once and exit                   │
│ --help                       Show this message and exit.                     │
╰──────────────────────────────────────────────────────────────────────────────╯
```

### `hq why`

```text
Usage: hq why [OPTIONS] {job_id}

 Explain why a job is currently waiting in the queue.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    job_id      <str>  Job ID to explain [required]                         │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --admin                 Assert explicit administrative elevation             │
│ --user   -u      <str>  Requesting username [default: default]               │
│ --help                  Show this message and exit.                          │
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
 notify: Optional list of notification destination URLs.
 notify_on: Comma- or pipe-separated lifecycle triggers.
 db_path: SQLite state store database path.
 watch: Whether to block and watch until terminal completion.
 format_type: Output presentation format.

╭─ Arguments ──────────────────────────────────────────────────────────────────╮
│ *    target      <str>  Path to workflow file, e.g. 'pipeline.py' or         │
│                         'pipeline.py:my_flow'                                │
│                         [required]                                           │
╰──────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────╮
│ --inputs     -i      <str>  JSON dictionary of initial inputs                │
│ --notify     -n      <str>  Notification targets (e.g. slack://...,          │
│                             pagerduty://...)                                 │
│ --notify-on          <str>  Lifecycle triggers (e.g. COMPLETED, FAILED,      │
│                             ERRORS, ALL)                                     │
│                             [default: ERRORS]                                │
│ --db                 <str>  Path to SQLite state database                    │
│                             [default: .hexaflow/state.db]                    │
│ --watch      -w             Watch workflow execution until completion        │
│ --format     -f      <str>  Output presentation format (table, json,         │
│                             markdown, rich, plain, auto).                    │
│                             [default: table]                                 │
│ --help                      Show this message and exit.                      │
╰──────────────────────────────────────────────────────────────────────────────╯
```
