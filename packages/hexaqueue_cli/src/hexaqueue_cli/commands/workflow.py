"""CLI commands for Hexaflow distributed workflow management in Hexaqueue.

Notes/Architectural Intent:
    Provides subcommands for submitting workflow DAG definitions to the cluster,
    inspecting step checkpoints and staged artifact URIs, resuming suspended workflows,
    and aborting active workflows with reverse compensation unwinding.
"""

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

import typer
from hexaflow.adapters.storage.sqlite import SqliteStateStore
from hexaflow.domain.models import WorkflowDefinition
from hexaflow.domain.state import StepStatus, WorkflowStatus
from hexaflow.dsl.builder import Workflow
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from hexaqueue_workflow.adapters.engines.distributed import HexaqueueDistributedEngine
from hexaqueue_workflow.domain.models import ArtifactReference

app = typer.Typer(
    name="workflow",
    help="Hexaflow distributed workflow orchestration and cluster scheduling commands.",
    no_args_is_help=True,
)
console = Console()


def load_workflow_from_target(target: str) -> WorkflowDefinition:
    """Dynamically load a Workflow or WorkflowDefinition from a file target.

    Supports 'path/to/file.py:workflow_name' or 'path/to/file.py' looking for
    the 'workflow' variable or an instance of Workflow/WorkflowDefinition.

    Args:
        target: String path or module identifier (e.g. 'flows/pipeline.py:main_flow').

    Returns:
        Compiled WorkflowDefinition.

    Raises:
        typer.BadParameter: If file or workflow variable cannot be loaded.

    Notes/Architectural Intent:
        Enables seamless loading of user-defined DAG workflows without requiring
        prior compilation or separate registration steps.
    """
    if ":" in target:
        file_part, attr_name = target.split(":", 1)
    else:
        file_part, attr_name = target, None

    file_path = Path(file_part).resolve()
    if not file_path.exists():
        msg = f"Workflow file '{file_path}' does not exist"
        raise typer.BadParameter(msg)

    spec = importlib.util.spec_from_file_location("dynamic_workflow_module", file_path)
    if not spec or not spec.loader:
        msg = f"Cannot load Python module from '{file_path}'"
        raise typer.BadParameter(msg)

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    wf_candidate: Any = None
    if attr_name:
        if not hasattr(module, attr_name):
            msg = f"Module '{file_path}' does not define attribute '{attr_name}'"
            raise typer.BadParameter(msg)
        wf_candidate = getattr(module, attr_name)
    else:
        if hasattr(module, "workflow"):
            wf_candidate = module.workflow
        else:
            for item in vars(module).values():
                if isinstance(item, (Workflow, WorkflowDefinition)):
                    wf_candidate = item
                    break

    if wf_candidate is None:
        msg = f"No Workflow or WorkflowDefinition instance found in '{file_path}'"
        raise typer.BadParameter(msg)

    if isinstance(wf_candidate, Workflow):
        return wf_candidate.compile()
    if isinstance(wf_candidate, WorkflowDefinition):
        return wf_candidate

    msg = f"Target object '{wf_candidate}' is not a Workflow or WorkflowDefinition"
    raise typer.BadParameter(msg)


def parse_inputs_arg(inputs: str | None) -> dict[str, Any]:
    """Parse JSON string or key=val pairs into a dictionary.

    Args:
        inputs: Raw CLI inputs argument string.

    Returns:
        Dictionary of input arguments.

    Raises:
        typer.BadParameter: If JSON decoding fails.
    """
    if not inputs:
        return {}
    try:
        parsed = json.loads(inputs)
        if isinstance(parsed, dict):
            return parsed
        msg = "Input JSON must be an object/dict"
        raise ValueError(msg)
    except Exception as e:
        msg = f"Invalid JSON inputs string: {e}"
        raise typer.BadParameter(msg) from e


@app.command("submit")
def submit_cmd(
    target: str = typer.Argument(
        ...,
        help="Path to workflow file, e.g. 'pipeline.py' or 'pipeline.py:my_flow'",
    ),
    inputs: str | None = typer.Option(
        None, "--inputs", "-i", help="JSON dictionary of initial inputs"
    ),
    db_path: str = typer.Option(
        ".hexaflow/state.db", "--db", help="Path to SQLite state database"
    ),
    watch: bool = typer.Option(
        False, "--watch", "-w", help="Watch workflow execution until completion"
    ),
) -> None:
    """Submit a workflow definition for distributed cluster execution.

    Args:
        target: Target file path or specifier.
        inputs: Optional JSON inputs string.
        db_path: SQLite state store database path.
        watch: Whether to block and watch until terminal completion.
    """
    workflow = load_workflow_from_target(target)
    initial_inputs = parse_inputs_arg(inputs)

    store = SqliteStateStore(db_path=db_path)
    engine = HexaqueueDistributedEngine(state_store=store)

    console.print(
        f"[bold green]Submitting workflow:[/] [cyan]{workflow.name}[/] "
        f"({len(workflow.stages)} stages, {sum(len(s.steps) for s in workflow.stages)} steps)"
    )

    async def _execute() -> None:
        state = await engine.run_async(workflow, initial_inputs=initial_inputs)
        _render_workflow_state(state, store)

    asyncio.run(_execute())


@app.command("status")
def status_cmd(
    run_id: str = typer.Argument(
        ..., help="Workflow execution run identifier to inspect"
    ),
    db_path: str = typer.Option(
        ".hexaflow/state.db", "--db", help="Path to SQLite state database"
    ),
) -> None:
    """Inspect status, checkpoints, and staged artifacts for a workflow run.

    Args:
        run_id: Run identifier to query.
        db_path: SQLite state store database path.
    """
    store = SqliteStateStore(db_path=db_path)
    state = store.get_run(run_id)

    if not state:
        console.print(
            f"[bold red]Error:[/] Workflow run '{run_id}' not found in database '{db_path}'."
        )
        raise typer.Exit(code=1)

    _render_workflow_state(state, store)


@app.command("resume")
def resume_cmd(
    run_id: str = typer.Argument(..., help="Suspended workflow run identifier"),
    target: str = typer.Argument(
        ...,
        help="Path to workflow file, e.g. 'pipeline.py' or 'pipeline.py:my_flow'",
    ),
    inputs: str | None = typer.Option(
        None, "--inputs", "-i", help="Patch inputs for resuming step frontier"
    ),
    skip_steps: list[str] = typer.Option(
        None, "--skip", help="Step names to explicitly skip"
    ),
    db_path: str = typer.Option(
        ".hexaflow/state.db", "--db", help="Path to SQLite state database"
    ),
) -> None:
    """Resume execution of a suspended workflow run from its latest checkpoints.

    Args:
        run_id: Suspended run identifier.
        target: Target workflow file specifier.
        inputs: Optional patch inputs.
        skip_steps: Optional step names to skip.
        db_path: SQLite state database path.
    """
    workflow = load_workflow_from_target(target)
    patch_inputs = parse_inputs_arg(inputs)

    store = SqliteStateStore(db_path=db_path)
    engine = HexaqueueDistributedEngine(state_store=store)

    console.print(f"[bold yellow]Resuming workflow run:[/] [cyan]{run_id}[/]")

    async def _resume() -> None:
        state = await engine.resume_async(
            run_id=run_id,
            workflow=workflow,
            patch_inputs=patch_inputs,
            skip_steps=set(skip_steps or ()),
        )
        _render_workflow_state(state, store)

    asyncio.run(_resume())


@app.command("abort")
def abort_cmd(
    run_id: str = typer.Argument(..., help="Workflow run identifier to abort"),
    target: str = typer.Argument(..., help="Path to workflow file"),
    db_path: str = typer.Option(
        ".hexaflow/state.db", "--db", help="Path to SQLite state database"
    ),
) -> None:
    """Abort an active or suspended workflow, unwinding step compensations in reverse order.

    Args:
        run_id: Run identifier to abort.
        target: Workflow file specifier containing compensations.
        db_path: SQLite state database path.
    """
    workflow = load_workflow_from_target(target)
    store = SqliteStateStore(db_path=db_path)
    engine = HexaqueueDistributedEngine(state_store=store)

    console.print(f"[bold red]Aborting workflow run:[/] [cyan]{run_id}[/]")

    async def _abort() -> None:
        state = await engine.abort_async(run_id=run_id, workflow=workflow)
        _render_workflow_state(state, store)

    asyncio.run(_abort())


def _render_workflow_state(state: Any, store: SqliteStateStore) -> None:
    """Render Rich status summary panel and step checkpoint table."""
    status_color = {
        WorkflowStatus.COMPLETED: "bold green",
        WorkflowStatus.RUNNING: "bold cyan",
        WorkflowStatus.SUSPENDED: "bold yellow",
        WorkflowStatus.CANCELLED: "bold magenta",
        WorkflowStatus.PENDING: "bold white",
    }.get(state.status, "white")

    header_table = Table.grid(padding=(0, 2))
    header_table.add_column(style="bold")
    header_table.add_column()
    header_table.add_row("Run ID:", state.run_id)
    header_table.add_row("Workflow:", state.workflow_name)
    header_table.add_row("Status:", f"[{status_color}]{state.status.value}[/]")
    if state.current_stage:
        header_table.add_row("Current Stage:", state.current_stage)
    if state.error_summary:
        header_table.add_row("Error:", f"[bold red]{state.error_summary}[/]")
    header_table.add_row(
        "Started At:", state.started_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    )
    if state.finished_at:
        header_table.add_row(
            "Finished At:", state.finished_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        )

    console.print(
        Panel(
            header_table,
            title=f"Workflow Run: {state.workflow_name}",
            expand=False,
        )
    )

    checkpoints = store.get_checkpoints(state.run_id)
    if not checkpoints:
        console.print("[dim]No step checkpoints recorded yet.[/]")
        return

    table = Table(title="Step Checkpoints & Staged Artifacts", expand=True)
    table.add_column("Stage", style="cyan")
    table.add_column("Step", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Attempt", justify="right")
    table.add_column("Duration (s)", justify="right")
    table.add_column("Artifact / Output", style="dim")

    for chk in checkpoints:
        chk_color = {
            StepStatus.COMPLETED: "[green]COMPLETED[/]",
            StepStatus.RUNNING: "[cyan]RUNNING[/]",
            StepStatus.FAILED: "[red]FAILED[/]",
            StepStatus.SKIPPED: "[dim]SKIPPED[/]",
            StepStatus.PENDING: "[white]PENDING[/]",
        }.get(chk.status, str(chk.status))

        artifact_info = "-"
        if ArtifactReference.is_artifact_envelope(chk.output_payload):
            uri = chk.output_payload.get("storage_uri", "")
            size = chk.output_payload.get("size_bytes", 0)
            artifact_info = f"[cyan]staged:[/] {uri} ({size}B)"
        elif chk.output_payload is not None:
            raw_str = str(chk.output_payload)
            artifact_info = (raw_str[:30] + "...") if len(raw_str) > 30 else raw_str

        table.add_row(
            chk.stage_name,
            chk.step_name,
            chk_color,
            str(chk.attempt_number),
            f"{chk.duration_seconds:.3f}",
            artifact_info,
        )

    console.print(table)


__all__ = [
    "abort_cmd",
    "app",
    "load_workflow_from_target",
    "parse_inputs_arg",
    "resume_cmd",
    "status_cmd",
    "submit_cmd",
]
