"""CLI subcommand group for hierarchical suite execution.

Notes/Architectural Intent:
    Provides `hq suite run` command to compile and submit multi-task,
    matrix-parameterized workloads into the cluster, maintaining parity
    with the `/suites` REST and `/dashboard/suites` Web endpoints.
"""

import asyncio
from pathlib import Path

import typer
import yaml
from rich.console import Console

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.adapters.presenter import CliPresenter
from hexaqueue_cli.infra.options import format_option, resolve_format
from hexaqueue_core.domain.suite import SuiteSpec

app = typer.Typer(
    name="suite",
    help="Manage and execute hierarchical suite workloads and parameter sweeps",
    no_args_is_help=True,
)
console = Console()


@app.command("run")
def run_suite_cmd(
    suite_file: Path = typer.Argument(
        ...,
        help="Path to suite specification YAML or JSON file",
        exists=True,
        readable=True,
    ),
    user: str = typer.Option(
        "default",
        "--user",
        "-u",
        help="User identity submitting the suite workload",
    ),
    admin: bool = typer.Option(
        False,
        "--admin",
        help="Assert explicit administrative elevation for privileged execution",
    ),
    format_type: str = format_option(),
) -> None:
    """Compile and submit a hierarchical suite workload.

    Args:
        suite_file: Path to YAML or JSON suite specification.
        user: Submitting user identity.
        admin: Administrative elevation flag.
        format_type: Chosen serialization output format.

    Notes/Architectural Intent:
        Flattens multi-level parameter inheritance, matrix sweeps, and DAG
        dependencies, dispatching to the underlying execution engine.
    """
    resolved_fmt = resolve_format(format_type)
    presenter = CliPresenter(console=console)

    with suite_file.open("r", encoding="utf-8") as f:
        raw_data = yaml.safe_load(f)

    try:
        suite_spec = SuiteSpec.model_validate(raw_data)
    except Exception as exc:
        console.print(f"[bold red]Failed to parse suite specification:[/] {exc}")
        raise typer.Exit(code=1) from exc

    async def _submit() -> None:
        client = LocalClientAdapter()
        try:
            report = await client.submit_suite(
                suite=suite_spec, user_id=user, elevate=admin
            )
            console.print(
                f"[bold green]✓[/] Suite workload submitted successfully as run '[bold cyan]{report.run_id}[/]'"
            )
            presenter.render_run_status(report, resolved_fmt)
        except Exception as exc:
            console.print(f"[bold red]Error submitting suite workload:[/] {exc}")
            raise typer.Exit(code=1) from exc

    asyncio.run(_submit())


__all__ = [
    "app",
]
